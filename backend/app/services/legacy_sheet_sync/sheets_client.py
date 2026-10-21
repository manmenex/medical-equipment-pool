"""Read-only Google Sheets v4 client (service account, REST over httpx).

Only the ``spreadsheets.readonly`` scope is ever requested and only GET
``values`` is ever called, so this module cannot modify the sheet. The
service-account JWT assertion is signed with ``google.auth`` (crypt + jwt);
no token, key content or key path is logged or put into an error message.
"""
import json
import time
from typing import Protocol
from urllib.parse import quote

import httpx
from google.auth import crypt, jwt

from app.services.legacy_sheet_sync.config import SyncConfigError

SCOPE_READONLY = "https://www.googleapis.com/auth/spreadsheets.readonly"
# Fixed on purpose: never follow a token_uri taken from the key file.
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
TIMEOUT = httpx.Timeout(30.0)


class SheetsError(RuntimeError):
    """Fetch failure. Fixed-text messages (HTTP status only)."""


class SheetReader(Protocol):
    async def read_tab(self, title: str) -> list[list[str]]: ...


def _load_signer_and_email(key_file: str) -> tuple[crypt.Signer, str]:
    try:
        with open(key_file, encoding="utf-8") as fh:
            info = json.load(fh)
        signer = crypt.RSASigner.from_service_account_info(info)
        email = info["client_email"]
    except (OSError, ValueError, KeyError, TypeError):
        # Deliberately generic: no path, no exception text (which could echo
        # key material or the path).
        raise SyncConfigError("The service-account key file is missing, unreadable or invalid.") from None
    return signer, email


class GoogleSheetsReader:
    def __init__(self, key_file: str, spreadsheet_id: str, client: httpx.AsyncClient | None = None):
        self._key_file = key_file
        self._spreadsheet_id = spreadsheet_id
        self._client = client
        self._token: str | None = None
        self._token_expiry = 0.0

    async def _get_token(self, http: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        signer, email = _load_signer_and_email(self._key_file)
        now = int(time.time())
        assertion = jwt.encode(
            signer,
            {"iss": email, "scope": SCOPE_READONLY, "aud": TOKEN_URL, "iat": now, "exp": now + 3600},
        )
        resp = await http.post(
            TOKEN_URL,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion.decode("ascii")},
        )
        if resp.status_code != 200:
            raise SheetsError(f"Google token request failed (HTTP {resp.status_code}).")
        body = resp.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + int(body.get("expires_in", 3600))
        return self._token

    async def read_tab(self, title: str) -> list[list[str]]:
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            token = await self._get_token(http)
            url = f"{SHEETS_BASE}/{quote(self._spreadsheet_id, safe='')}/values/{quote(chr(39) + title + chr(39), safe='')}"
            resp = await http.get(
                url,
                params={"valueRenderOption": "FORMATTED_VALUE", "majorDimension": "ROWS"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                raise SheetsError(f"Google Sheets read failed (HTTP {resp.status_code}). Is the sheet shared with the service account?")
            return [[str(c) for c in row] for row in resp.json().get("values", [])]
        except httpx.HTTPError as exc:
            raise SheetsError(f"Network error reading the sheet ({type(exc).__name__}).") from None
        finally:
            if owns:
                await http.aclose()
