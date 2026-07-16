"""
Secure credential storage for third-party portal logins (ECRI, etc.).

Security requirements addressed:
    - Passwords are NEVER hardcoded or stored in plain text/config files.
    - Primary backend: the `keyring` package, which transparently uses the
      Windows Credential Manager on Windows, Keychain on macOS, and the
      Freedesktop Secret Service (or KWallet) on Linux.
    - Fallback backend: when no OS keyring backend is available (e.g. a
      minimal/headless Linux box with nothing providing the Secret
      Service - common on servers running the scheduled/background mode),
      credentials are encrypted at rest with a locally-generated Fernet
      key (AES-128-CBC + HMAC) stored in a file with owner-only
      permissions. This is strictly better than plain text and keeps the
      app functional everywhere, while the OS vault remains preferred.
"""

from __future__ import annotations

import json
import os
import platform
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, TypeVar

from app.models.credential import CredentialInfo
from app.utils.exceptions import CredentialError
from app.utils.logging_config import get_audit_logger, get_logger

logger = get_logger(__name__)
audit_login = get_audit_logger("login")

try:
    import keyring
    from keyring.errors import KeyringError

    _KEYRING_AVAILABLE = True
except ImportError:  # pragma: no cover
    _KEYRING_AVAILABLE = False

    class KeyringError(Exception):  # type: ignore[no-redef]
        pass


_APP_NAMESPACE = "MedicalDeviceRecallMonitor"

_T = TypeVar("_T")


def _run_with_timeout(fn, timeout: float):
    """Run `fn()` with a hard wall-clock timeout, raising on expiry.

    Used to stop slow/hanging OS credential-backend probing (e.g. D-Bus
    Secret Service calls with no listener) from blocking app startup.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout)
    finally:
        # wait=False: if `fn` is stuck (e.g. a hung D-Bus call), don't let
        # shutdown() block the caller too - the worker thread is a daemon
        # of the process and will be reclaimed when the process exits.
        executor.shutdown(wait=False)


@dataclass
class _StoredSecret:
    username: str
    password: str
    updated_at: str


class _EncryptedFileBackend:
    """Fallback secret store used when no OS keyring backend is present."""

    def __init__(self, data_dir: Path):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._key_path = self._data_dir / ".cred.key"
        self._store_path = self._data_dir / "credentials.enc"
        self._fernet = self._load_or_create_key()

    def _load_or_create_key(self):
        from cryptography.fernet import Fernet

        if self._key_path.exists():
            key = self._key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            self._key_path.write_bytes(key)
            try:
                os.chmod(self._key_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:  # pragma: no cover - best effort on non-POSIX FS
                pass
        return Fernet(key)

    def _load_store(self) -> dict:
        if not self._store_path.exists():
            return {}
        try:
            encrypted = self._store_path.read_bytes()
            decrypted = self._fernet.decrypt(encrypted)
            return json.loads(decrypted.decode("utf-8"))
        except Exception as exc:  # pragma: no cover - corrupted/foreign file
            logger.error("Failed to read encrypted credential store: %s", exc)
            return {}

    def _save_store(self, store: dict) -> None:
        payload = json.dumps(store).encode("utf-8")
        encrypted = self._fernet.encrypt(payload)
        self._store_path.write_bytes(encrypted)
        try:
            os.chmod(self._store_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover
            pass

    def set_password(self, service: str, username: str, password: str) -> None:
        store = self._load_store()
        store[service] = {
            "username": username,
            "password": password,
            "updated_at": datetime.now().isoformat(),
        }
        self._save_store(store)

    def get_password(self, service: str) -> Optional[_StoredSecret]:
        store = self._load_store()
        entry = store.get(service)
        if not entry:
            return None
        return _StoredSecret(entry["username"], entry["password"], entry.get("updated_at", ""))

    def delete_password(self, service: str) -> None:
        store = self._load_store()
        store.pop(service, None)
        self._save_store(store)


class CredentialService:
    """Facade over keyring (preferred) / encrypted file (fallback)."""

    def __init__(self, data_dir: Path):
        self._fallback = _EncryptedFileBackend(data_dir)
        self._use_keyring = _KEYRING_AVAILABLE and self._keyring_usable()

    def _keyring_usable(self) -> bool:
        if not _KEYRING_AVAILABLE:
            return False

        # On headless Linux (typical for a server running only the
        # scheduled/background checks, with no desktop session), keyring's
        # backend probing tries to reach the Freedesktop Secret Service over
        # D-Bus and can hang for a long time waiting for a bus that will
        # never appear. Detect that case up front and go straight to the
        # encrypted-file fallback instead of blocking application startup.
        if platform.system() == "Linux" and not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            logger.info("No D-Bus session detected; using encrypted-file credential storage.")
            return False

        try:
            backend = _run_with_timeout(keyring.get_keyring, timeout=2.0)
            # A "fail" backend indicates no real vault is available.
            return "fail" not in backend.__class__.__module__.lower()
        except Exception:  # pragma: no cover
            return False

    def save_credentials(self, service_name: str, username: str, password: str) -> None:
        """Persist credentials for `service_name` (e.g. 'ECRI')."""
        key = f"{_APP_NAMESPACE}:{service_name}"
        try:
            if self._use_keyring:
                keyring.set_password(key, username, password)
                # Remember which username belongs to this service (keyring is
                # keyed by username, so we store a small pointer alongside).
                keyring.set_password(key, "__last_username__", username)
            else:
                self._fallback.set_password(service_name, username, password)
            audit_login.info("Credentials saved for service=%s user=%s", service_name, username)
        except KeyringError as exc:
            logger.warning("Keyring backend failed (%s); falling back to encrypted file store", exc)
            self._fallback.set_password(service_name, username, password)
        except Exception as exc:  # pragma: no cover - defensive
            raise CredentialError(f"Failed to save credentials for {service_name}: {exc}") from exc

    def get_credentials(self, service_name: str) -> Optional[tuple[str, str]]:
        """Return (username, password) for `service_name`, or None if unset."""
        key = f"{_APP_NAMESPACE}:{service_name}"
        try:
            if self._use_keyring:
                username = keyring.get_password(key, "__last_username__")
                if not username:
                    return None
                password = keyring.get_password(key, username)
                if password is None:
                    return None
                return username, password
        except KeyringError as exc:
            logger.warning("Keyring read failed (%s); trying encrypted file store", exc)
        except Exception as exc:  # pragma: no cover
            logger.error("Unexpected keyring error: %s", exc)

        secret = self._fallback.get_password(service_name)
        return (secret.username, secret.password) if secret else None

    def has_credentials(self, service_name: str) -> bool:
        return self.get_credentials(service_name) is not None

    def delete_credentials(self, service_name: str) -> None:
        key = f"{_APP_NAMESPACE}:{service_name}"
        try:
            if self._use_keyring:
                username = keyring.get_password(key, "__last_username__")
                if username:
                    keyring.delete_password(key, username)
                    keyring.delete_password(key, "__last_username__")
        except Exception as exc:  # pragma: no cover
            logger.debug("Keyring delete no-op/failed: %s", exc)
        self._fallback.delete_password(service_name)
        audit_login.info("Credentials deleted for service=%s", service_name)

    def get_info(self, service_name: str) -> CredentialInfo:
        creds = self.get_credentials(service_name)
        if creds:
            return CredentialInfo(service_name=service_name, username=creds[0], is_configured=True)
        return CredentialInfo(service_name=service_name, username="", is_configured=False)


_INSTANCE: CredentialService | None = None


def get_credential_service() -> CredentialService:
    global _INSTANCE
    if _INSTANCE is None:
        from app.config import get_settings

        _INSTANCE = CredentialService(get_settings().data_dir)
    return _INSTANCE
