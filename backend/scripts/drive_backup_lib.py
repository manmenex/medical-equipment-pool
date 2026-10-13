"""PR25A: off-host backup to Google Drive -- the tested logic.

docs/DECISION_LOG.md (2026-10-13, "Local Production on the department host"):
every hourly backup is copied off the host to the department's Google Drive.

Design, in one place so the reasoning is not lost:

* AUTH. The department uses a consumer Gmail account. A service account has
  no Drive storage quota there, so the tool acts AS the account through
  OAuth user consent, given once with the OAuth *device flow* (no browser on
  the host, no loopback port to publish out of a container). The narrow
  ``drive.file`` scope is requested: the tool can only see files it created
  itself, never the rest of the Drive. The resulting refresh token is kept in
  a local secret file (0600 where the OS supports it; the PowerShell wrapper
  applies an ACL on Windows) and is never logged, printed, or placed in an
  exception message or the upload state file.
* NO GOOGLE SDK. Four REST calls over ``httpx`` (already a dependency).
* PENDING QUEUE IS DERIVED, NOT STORED. A local backup (dump + manifest) that
  the state file does not list as uploaded is pending. There is no second
  list that could drift from the disk. A failed upload leaves the local
  backup untouched and simply stays pending until the next run.
* IDEMPOTENT. Each run lists the Drive folder first; anything already there
  with a matching size is not re-uploaded. That makes retries safe after a
  half-finished run, heals a lost state file, and stops a restored-to-new-PC
  backup from being uploaded twice.
* RETENTION. ``pg_backup_lib.select_tiered_prune_candidates`` is reused
  unchanged (48h all, newest per UTC day to 30 days, newest never deleted).
  Nothing here re-implements the tiers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from scripts.pg_backup_lib import (
    DEFAULT_HOURLY_RETENTION_HOURS,
    DEFAULT_RETENTION_DAYS,
    manifest_filename_for,
    parse_backup_filename,
    select_tiered_prune_candidates,
    sha256_checksum,
    utc_now,
)

SCOPE = "https://www.googleapis.com/auth/drive.file"
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_FOLDER_NAME = "MEP Database Backups"

SECRETS_FILENAME = "drive-oauth.json"
STATE_FILENAME = ".drive-upload-state.json"
LOCK_FILENAME = ".drive-upload.lock"
STALE_LOCK_SECONDS = 4 * 3600

_CHUNK = 1024 * 1024
_TIMEOUT = httpx.Timeout(connect=30.0, read=300.0, write=300.0, pool=30.0)
_RETRYABLE = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Errors and secret hygiene
# ---------------------------------------------------------------------------

_SECRET_VALUES: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember a secret so scrub() can remove it from any text."""
    if value and len(value) >= 6:
        _SECRET_VALUES.add(value)


def scrub(text: str) -> str:
    """Remove every registered secret (and bearer tokens) from `text`."""
    for secret in _SECRET_VALUES:
        text = text.replace(secret, "***")
    return re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", text)


class DriveError(Exception):
    """A Drive/OAuth failure whose message is safe to log and print.

    `systemic` means retrying other files this run is pointless (auth
    rejected, network down); a per-file problem is not systemic.
    """

    def __init__(self, message: str, *, systemic: bool = False, status: int | None = None):
        super().__init__(scrub(message))
        self.systemic = systemic
        self.status = status


class DriveAuthError(DriveError):
    def __init__(self, message: str):
        super().__init__(message, systemic=True)


class DriveBusy(Exception):
    """Another upload run holds the lock."""


# ---------------------------------------------------------------------------
# Secret file
# ---------------------------------------------------------------------------


@dataclass
class DriveConfig:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    refresh_token: str = field(repr=False)
    folder_id: str
    folder_name: str = DEFAULT_FOLDER_NAME

    def __post_init__(self) -> None:
        for secret in (self.client_id, self.client_secret, self.refresh_token):
            register_secret(secret)


_REQUIRED_KEYS = ("client_id", "client_secret", "refresh_token", "folder_id")


def secrets_file_configured(path: Path) -> bool:
    """True when the file exists and has every key. Never returns a value."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and all(isinstance(data.get(k), str) and data[k] for k in _REQUIRED_KEYS)


def load_config(path: Path) -> DriveConfig:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DriveError(f"Drive backup is not set up: {path.name} not found. Run the setup command.", systemic=True) from None
    except (OSError, ValueError):
        raise DriveError(f"{path.name} is unreadable or not valid JSON. Re-run the setup command.", systemic=True) from None
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k] for k in _REQUIRED_KEYS):
        raise DriveError(f"{path.name} is incomplete. Re-run the setup command.", systemic=True)
    return DriveConfig(
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        refresh_token=data["refresh_token"],
        folder_id=data["folder_id"],
        folder_name=str(data.get("folder_name") or DEFAULT_FOLDER_NAME),
    )


def write_secret_file(path: Path, payload: dict[str, str]) -> None:
    """Atomic write, created 0600 (POSIX) so it is never briefly world-readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-secret-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Drive client
# ---------------------------------------------------------------------------


def _error_reason(response: httpx.Response) -> str:
    """Google's own error code/message only -- never the request."""
    try:
        body = response.json()
    except ValueError:
        return "no error detail"
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        errors = err.get("errors") or [{}]
        reason = errors[0].get("reason") if isinstance(errors[0], dict) else None
        return str(reason or err.get("status") or err.get("message") or "unknown")[:200]
    if isinstance(err, str):
        return err[:200]
    return "unknown"


class DriveClient:
    def __init__(
        self,
        config: DriveConfig,
        *,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._http = http or httpx.Client(timeout=_TIMEOUT)
        self._sleep = sleep
        self._access_token: str | None = None

    # -- auth ---------------------------------------------------------------
    def _refresh_access_token(self) -> str:
        try:
            response = self._http.post(
                TOKEN_URL,
                data={
                    "client_id": self._config.client_id,
                    "client_secret": self._config.client_secret,
                    "refresh_token": self._config.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as exc:
            raise DriveError(f"network error contacting Google OAuth ({type(exc).__name__})", systemic=True) from None
        if response.status_code != 200:
            reason = _error_reason(response)
            if reason == "invalid_grant" or response.status_code in (400, 401):
                raise DriveAuthError(
                    f"Google rejected the stored refresh token ({reason}). Re-run the setup command. "
                    "If the OAuth consent screen is still in 'Testing' status, tokens expire after 7 days: "
                    "publish the app ('In production') first."
                )
            raise DriveError(f"token refresh failed (HTTP {response.status_code}: {reason})", systemic=True)
        token = response.json().get("access_token")
        if not token:
            raise DriveAuthError("Google returned no access token")
        register_secret(token)
        self._access_token = token
        return token

    def _auth_headers(self) -> dict[str, str]:
        token = self._access_token or self._refresh_access_token()
        return {"Authorization": f"Bearer {token}"}

    # -- plumbing -----------------------------------------------------------
    def _request(
        self,
        method: str,
        url: str,
        *,
        expect: tuple[int, ...] = (200,),
        attempts: int = 3,
        **kwargs: Any,
    ) -> httpx.Response:
        refreshed = False
        base_headers = kwargs.pop("headers", {})
        for attempt in range(1, attempts + 1):
            headers = {**base_headers, **self._auth_headers()}
            try:
                response = self._http.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                if attempt < attempts:
                    self._sleep(2**attempt)
                    continue
                raise DriveError(f"network error talking to Google Drive ({type(exc).__name__})", systemic=True) from None
            if response.status_code in expect:
                return response
            if response.status_code == 401 and not refreshed:
                refreshed = True
                self._access_token = None
                continue
            if response.status_code in _RETRYABLE and attempt < attempts:
                self._sleep(2**attempt)
                continue
            reason = _error_reason(response)
            raise DriveError(
                f"Drive API {method} failed (HTTP {response.status_code}: {reason})",
                systemic=response.status_code in (401, 403) and reason in {"authError", "insufficientPermissions"},
                status=response.status_code,
            )
        raise DriveError("Drive API request exhausted its retries", systemic=True)  # pragma: no cover

    # -- folder -------------------------------------------------------------
    def find_or_create_folder(self, name: str) -> str:
        """Reuse a folder this app already created (so a second PC joins the
        same folder) before creating one."""
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        found = self._request(
            "GET",
            f"{DRIVE_API}/files",
            params={
                "q": f"name = '{escaped}' and mimeType = '{FOLDER_MIME}' and trashed = false",
                "fields": "files(id,name)",
                "pageSize": "10",
                "orderBy": "createdTime",
            },
        ).json()
        files = found.get("files") or []
        if files:
            return str(files[0]["id"])
        created = self._request(
            "POST", f"{DRIVE_API}/files", params={"fields": "id"}, json={"name": name, "mimeType": FOLDER_MIME}
        ).json()
        return str(created["id"])

    def list_folder(self, folder_id: str) -> dict[str, dict[str, Any]]:
        """name -> {id, size, md5Checksum}. Newest wins if a name repeats."""
        result: dict[str, dict[str, Any]] = {}
        page_token: str | None = None
        while True:
            params = {
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": "nextPageToken,files(id,name,size,md5Checksum,createdTime)",
                "pageSize": "1000",
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                body = self._request("GET", f"{DRIVE_API}/files", params=params).json()
            except DriveError as exc:
                if exc.status == 404:
                    raise DriveError(
                        "the Drive backup folder was not found (deleted?). Re-run the setup command.", systemic=True
                    ) from None
                raise
            for item in body.get("files", []):
                result[item["name"]] = item
            page_token = body.get("nextPageToken")
            if not page_token:
                return result

    def delete(self, file_id: str) -> None:
        self._request("DELETE", f"{DRIVE_API}/files/{file_id}", expect=(200, 204))

    # -- transfer -----------------------------------------------------------
    def upload_file(self, path: Path, *, name: str, folder_id: str) -> dict[str, Any]:
        size = path.stat().st_size
        init = self._request(
            "POST",
            DRIVE_UPLOAD,
            params={"uploadType": "resumable", "fields": "id,name,size,md5Checksum"},
            json={"name": name, "parents": [folder_id]},
            headers={"X-Upload-Content-Type": "application/octet-stream", "X-Upload-Content-Length": str(size)},
        )
        session_uri = init.headers.get("Location", "")
        if not session_uri.startswith("https://"):
            raise DriveError("Drive did not return a resumable upload session")
        try:
            with path.open("rb") as fh:
                response = self._http.put(
                    session_uri,
                    content=_read_chunks(fh),
                    headers={"Content-Length": str(size), "Content-Type": "application/octet-stream"},
                )
        except httpx.HTTPError as exc:
            raise DriveError(f"network error during upload ({type(exc).__name__})", systemic=True) from None
        if response.status_code not in (200, 201):
            raise DriveError(
                f"upload of {name} failed (HTTP {response.status_code}: {_error_reason(response)})",
                status=response.status_code,
            )
        meta = response.json()
        expected_md5 = _md5(path)
        if meta.get("md5Checksum") and meta["md5Checksum"].lower() != expected_md5:
            self.delete(meta["id"])
            raise DriveError(f"Drive reports a different checksum for {name}; the copy was removed and will be retried")
        if int(meta.get("size", size)) != size:
            self.delete(meta["id"])
            raise DriveError(f"Drive reports a different size for {name}; the copy was removed and will be retried")
        return meta

    def download_file(self, file_id: str, destination: Path) -> None:
        try:
            with self._http.stream(
                "GET", f"{DRIVE_API}/files/{file_id}", params={"alt": "media"}, headers=self._auth_headers()
            ) as response:
                if response.status_code != 200:
                    response.read()
                    raise DriveError(f"download failed (HTTP {response.status_code}: {_error_reason(response)})")
                with destination.open("wb") as out:
                    for chunk in response.iter_bytes(_CHUNK):
                        out.write(chunk)
        except httpx.HTTPError as exc:
            raise DriveError(f"network error during download ({type(exc).__name__})", systemic=True) from None


def _read_chunks(fh: Any) -> Iterator[bytes]:
    while chunk := fh.read(_CHUNK):
        yield chunk


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)  # Drive's own integrity field, not a security control
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# OAuth device flow (setup)
# ---------------------------------------------------------------------------


def run_device_flow(
    client_id: str,
    client_secret: str,
    *,
    http: httpx.Client,
    say: Callable[[str], None],
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> str:
    """Interactive consent. Returns the refresh token; prints only the
    verification URL and the short user code (neither is a secret)."""
    register_secret(client_id)
    register_secret(client_secret)
    try:
        started = http.post(DEVICE_CODE_URL, data={"client_id": client_id, "scope": SCOPE})
    except httpx.HTTPError as exc:
        raise DriveError(f"network error contacting Google ({type(exc).__name__})", systemic=True) from None
    if started.status_code != 200:
        raise DriveError(
            f"Google refused the device-code request (HTTP {started.status_code}: {_error_reason(started)}). "
            "Check the client ID, and that the OAuth client type is 'TVs and Limited Input devices'.",
            systemic=True,
        )
    info = started.json()
    device_code = info["device_code"]
    register_secret(device_code)
    interval = float(info.get("interval", 5))
    deadline = monotonic() + float(info.get("expires_in", 1800))
    say(f"Open {info['verification_url']} on any device, sign in as the department Google account,")
    say(f"and enter this code: {info['user_code']}")
    say("Waiting for approval...")
    while monotonic() < deadline:
        sleep(interval)
        try:
            polled = http.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
        except httpx.HTTPError as exc:
            raise DriveError(f"network error while waiting for consent ({type(exc).__name__})", systemic=True) from None
        if polled.status_code == 200:
            body = polled.json()
            refresh = body.get("refresh_token")
            if not refresh:
                raise DriveError("Google returned no refresh token; remove the app at myaccount.google.com/permissions and retry")
            register_secret(refresh)
            if SCOPE not in str(body.get("scope", SCOPE)):
                raise DriveError("consent did not grant the drive.file scope")
            return str(refresh)
        reason = _error_reason(polled)
        if reason == "authorization_pending":
            continue
        if reason == "slow_down":
            interval += 5
            continue
        if reason == "access_denied":
            raise DriveError("consent was declined")
        if reason == "expired_token":
            raise DriveError("the consent code expired; run setup again")
        raise DriveError(f"consent failed ({reason})")
    raise DriveError("timed out waiting for consent; run setup again")


# ---------------------------------------------------------------------------
# Local backups and upload state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocalBackup:
    dump: Path
    manifest: Path
    created_at: datetime

    @property
    def name(self) -> str:
        return self.dump.name


def local_backups(backup_dir: Path) -> list[LocalBackup]:
    """Complete local backups (dump AND manifest), newest first."""
    found: list[LocalBackup] = []
    if not backup_dir.is_dir():
        return found
    for entry in backup_dir.iterdir():
        parsed = parse_backup_filename(entry.name)
        if parsed is None or not entry.is_file():
            continue
        manifest = entry.with_name(manifest_filename_for(entry.name))
        if manifest.is_file():
            found.append(LocalBackup(entry, manifest, parsed[1]))
    return sorted(found, key=lambda b: b.created_at, reverse=True)


@dataclass
class UploadState:
    uploaded: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_uploaded_name: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None
    last_prune_error: str | None = None

    @classmethod
    def load(cls, path: Path) -> UploadState:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return cls()
            return cls(**{k: raw[k] for k in cls.__dataclass_fields__ if k in raw})
        except (OSError, ValueError, TypeError):
            return cls()  # corrupt/missing: re-derived from the Drive listing

    def save(self, path: Path) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-state-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.__dict__, fh, indent=2, sort_keys=True)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


class _Lock:
    def __init__(self, path: Path) -> None:
        self._path = path

    def __enter__(self) -> _Lock:
        for _ in range(2):
            try:
                fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if time.time() - self._path.stat().st_mtime > STALE_LOCK_SECONDS:
                        self._path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                raise DriveBusy("another Drive upload is already running") from None
            with os.fdopen(fd, "w") as fh:
                fh.write(str(os.getpid()))
            return self
        raise DriveBusy("another Drive upload is already running")

    def __exit__(self, *exc: object) -> None:
        self._path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Upload + retention
# ---------------------------------------------------------------------------


@dataclass
class UploadReport:
    uploaded: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    retired_by_retention: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    prune_error: str | None = None
    fatal: str | None = None

    @property
    def ok(self) -> bool:
        return not self.failed and self.fatal is None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _drive_dump_times(names: Any) -> list[tuple[Path, datetime]]:
    out = []
    for name in names:
        parsed = parse_backup_filename(name)
        if parsed is not None:
            out.append((Path(name), parsed[1]))
    return out


def _file_matches(entry: dict[str, Any] | None, path: Path) -> bool:
    return entry is not None and int(entry.get("size", -1)) == path.stat().st_size


def upload_pending(
    client: DriveClient,
    *,
    folder_id: str,
    backup_dir: Path,
    state_path: Path,
    now: datetime | None = None,
    hourly_retention_hours: int = DEFAULT_HOURLY_RETENTION_HOURS,
    daily_retention_days: int = DEFAULT_RETENTION_DAYS,
) -> UploadReport:
    """Upload every pending local backup, then apply Drive retention.

    NEVER touches, moves or deletes a local file, and never raises for a
    Drive problem: failures are recorded in the state file and returned.
    """
    now = now or utc_now()
    report = UploadReport()
    with _Lock(backup_dir / LOCK_FILENAME):
        state = UploadState.load(state_path)
        state.last_attempt_at = _iso(now)
        try:
            _run_upload(client, folder_id, backup_dir, state, report, now, hourly_retention_hours, daily_retention_days)
        except DriveError as exc:
            report.fatal = str(exc)
        if report.fatal:
            state.last_error, state.last_error_at = report.fatal, _iso(now)
        elif report.failed:
            state.last_error = "; ".join(f"{n}: {m}" for n, m in report.failed)[:1000]
            state.last_error_at = _iso(now)
        else:
            state.last_error = state.last_error_at = None
            state.last_success_at = _iso(now)
        state.last_prune_error = report.prune_error
        state.save(state_path)
    return report


def _run_upload(
    client: DriveClient,
    folder_id: str,
    backup_dir: Path,
    state: UploadState,
    report: UploadReport,
    now: datetime,
    hourly: int,
    daily: int,
) -> None:
    listing = client.list_folder(folder_id)  # a failure here is fatal for the run, local files untouched
    local = local_backups(backup_dir)
    pending = [b for b in local if b.name not in state.uploaded]

    # Do not upload what Drive retention would delete straight away (e.g. a
    # multi-day outage queued old hourly files). Same selection function.
    would_prune = {
        p.name
        for p in select_tiered_prune_candidates(
            _drive_dump_times({*listing, *(b.name for b in local)}),
            now=now,
            hourly_retention_hours=hourly,
            daily_retention_days=daily,
        )
    }
    for backup in list(pending):
        if backup.name in would_prune and backup.name not in listing:
            state.uploaded[backup.name] = {"retired": "retention"}
            report.retired_by_retention.append(backup.name)
            pending.remove(backup)

    systemic_failure = False
    for backup in pending:  # newest first
        try:
            _ensure_backup_on_drive(client, folder_id, backup, listing, report)
        except OSError as exc:  # e.g. the local file vanished mid-run
            report.failed.append((backup.name, f"local file error ({type(exc).__name__})"))
            continue
        except DriveError as exc:
            report.failed.append((backup.name, str(exc)))
            if exc.systemic:
                systemic_failure = True
                break
            continue
        state.uploaded[backup.name] = {"uploaded_at": _iso(now)}
        state.last_uploaded_name = backup.name

    # Forget bookkeeping for files long gone from disk (keeps the file small).
    horizon = now - timedelta(days=daily + 2)
    local_names = {b.name for b in local}
    for name in list(state.uploaded):
        parsed = parse_backup_filename(name)
        if name not in local_names and (parsed is None or parsed[1] < horizon):
            del state.uploaded[name]

    if systemic_failure:
        return  # Google unreachable/refusing: do not attempt deletes either
    _prune_drive(client, listing, report, now, hourly, daily)


def _ensure_backup_on_drive(
    client: DriveClient, folder_id: str, backup: LocalBackup, listing: dict[str, dict[str, Any]], report: UploadReport
) -> None:
    present = 0
    for path in (backup.dump, backup.manifest):  # dump first: a manifest alone never implies a usable backup
        existing = listing.get(path.name)
        if _file_matches(existing, path):
            present += 1
            continue
        if existing is not None:  # same name, wrong size: replace it
            client.delete(existing["id"])
        listing[path.name] = client.upload_file(path, name=path.name, folder_id=folder_id)
    (report.already_present if present == 2 else report.uploaded).append(backup.name)


def _prune_drive(
    client: DriveClient, listing: dict[str, dict[str, Any]], report: UploadReport, now: datetime, hourly: int, daily: int
) -> None:
    candidates = select_tiered_prune_candidates(
        _drive_dump_times(listing), now=now, hourly_retention_hours=hourly, daily_retention_days=daily
    )
    errors = []
    for candidate in candidates:
        try:
            for name in (candidate.name, manifest_filename_for(candidate.name)):
                entry = listing.get(name)
                if entry is not None:
                    client.delete(entry["id"])
                    listing.pop(name, None)
            report.pruned.append(candidate.name)
        except DriveError as exc:
            errors.append(f"{candidate.name}: {exc}")
            if exc.systemic:
                break
    if errors:
        report.prune_error = "; ".join(errors)[:1000]


# ---------------------------------------------------------------------------
# Status, list, download
# ---------------------------------------------------------------------------


def _age(now: datetime, then: datetime) -> str:
    minutes = int((now - then).total_seconds() // 60)
    return f"{minutes} min ago" if minutes < 120 else f"{minutes // 60} h ago"


def drive_status(
    *, secrets_file: Path, backup_dir: Path, state_path: Path, now: datetime | None = None
) -> tuple[list[str], bool]:
    """Offline status (no network). Returns (lines, healthy)."""
    now = now or utc_now()
    lines: list[str] = []
    healthy = True
    if not secrets_file_configured(secrets_file):
        return (["Drive backup:      NOT CONFIGURED (run the setup command; backups are NOT off-host)"], False)
    state = UploadState.load(state_path)
    local = local_backups(backup_dir)
    pending = [b for b in local if b.name not in state.uploaded]
    lines.append("Drive backup:      CONFIGURED")
    if local:
        lines.append(f"Last local backup: {local[0].name} ({_age(now, local[0].created_at)})")
    else:
        lines.append("Last local backup: none")
    if state.last_uploaded_name:
        lines.append(f"Last upload:       {state.last_uploaded_name} (run finished {state.last_success_at or 'with errors'})")
    else:
        lines.append("Last upload:       never")
    lines.append(f"Pending uploads:   {len(pending)}")
    if pending:
        healthy = False
        lines.append(f"  oldest pending:  {pending[-1].name}")
    if state.last_error:
        healthy = False
        lines.append(f"Last error:        {scrub(state.last_error)} (at {state.last_error_at})")
    if state.last_prune_error:
        lines.append(f"Retention warning: {scrub(state.last_prune_error)}")
    lines.append("STATUS: OK - Drive is up to date" if healthy else "STATUS: ATTENTION - off-host copy is behind")
    return lines, healthy


@dataclass(frozen=True)
class DriveBackup:
    name: str
    created_at: datetime
    size: int
    dump: dict[str, Any]
    manifest: dict[str, Any]


def list_drive_backups(client: DriveClient, folder_id: str) -> list[DriveBackup]:
    """Complete backups on Drive (dump + manifest both present), newest first."""
    listing = client.list_folder(folder_id)
    out = []
    for name, entry in listing.items():
        parsed = parse_backup_filename(name)
        manifest = listing.get(manifest_filename_for(name))
        if parsed and manifest:
            out.append(DriveBackup(name, parsed[1], int(entry.get("size", 0)), entry, manifest))
    return sorted(out, key=lambda b: b.created_at, reverse=True)


def download_backup(client: DriveClient, backup: DriveBackup, output_dir: Path) -> Path:
    """Download + verify one backup into `output_dir`; returns the dump path.

    Manifest first (it names the expected SHA-256 and size). The dump is
    written to a .partial file and only renamed after both match, so a
    truncated download can never look like a backup. restore_postgres.py
    verifies the checksum again independently.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    final = output_dir / backup.name
    manifest_final = output_dir / manifest_filename_for(backup.name)
    manifest_partial = manifest_final.with_name(manifest_final.name + ".partial")
    client.download_file(backup.manifest["id"], manifest_partial)
    try:
        manifest = json.loads(manifest_partial.read_text(encoding="utf-8"))
        expected_sha = str(manifest["checksum_sha256"]).lower()
        expected_size = int(manifest["file_size_bytes"])
    except (ValueError, KeyError, TypeError):
        manifest_partial.unlink(missing_ok=True)
        raise DriveError(f"the manifest for {backup.name} on Drive is unreadable") from None

    if final.is_file() and final.stat().st_size == expected_size and sha256_checksum(final) == expected_sha:
        os.replace(manifest_partial, manifest_final)
        return final  # already here and verified

    partial = final.with_name(final.name + ".partial")
    try:
        client.download_file(backup.dump["id"], partial)
        if partial.stat().st_size != expected_size or sha256_checksum(partial) != expected_sha:
            raise DriveError(f"downloaded {backup.name} does not match its manifest checksum; discarded")
        os.replace(partial, final)
        os.replace(manifest_partial, manifest_final)
    finally:
        partial.unlink(missing_ok=True)
        manifest_partial.unlink(missing_ok=True)
    return final
