"""PR25A: off-host Google Drive backup. All Google traffic is mocked with
httpx.MockTransport -- no network, no credentials."""

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from scripts import drive_backup
from scripts import drive_backup_lib as lib

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=timezone.utc)
REFRESH = "1//SECRET-REFRESH-TOKEN-abcdef"
CLIENT_SECRET = "SECRET-CLIENT-SECRET-123456"
ACCESS = "ya29.SECRET-ACCESS-TOKEN-xyz"
SENTINELS = (REFRESH, CLIENT_SECRET, ACCESS)
FOLDER = "folder-1"


def _name(ts: datetime) -> str:
    return f"mep-postgres-localstaging-{ts:%Y%m%dT%H%M%SZ}.dump"


def make_backup(directory: Path, ts: datetime, payload: bytes | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    dump = directory / _name(ts)
    data = payload if payload is not None else f"dump-{ts.isoformat()}".encode()
    dump.write_bytes(data)
    manifest = {"checksum_sha256": hashlib.sha256(data).hexdigest(), "file_size_bytes": len(data)}
    dump.with_name(dump.name + ".manifest.json").write_text(json.dumps(manifest))
    return dump


class FakeDrive:
    """Just enough of Drive v3 + OAuth for the client under test."""

    def __init__(self) -> None:
        self.files: dict[str, dict] = {}  # id -> {name, content}
        self.fail_upload_for: set[str] = set()
        self.token_status = 200
        self.offline = False
        self.calls: list[tuple[str, str]] = []
        self._n = 0
        self._pending: dict[str, str] = {}

    def seed(self, name: str, content: bytes) -> str:
        self._n += 1
        fid = f"id{self._n}"
        self.files[fid] = {"name": name, "content": content}
        return fid

    def names(self) -> set[str]:
        return {f["name"] for f in self.files.values()}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.offline:
            raise httpx.ConnectError("boom " + REFRESH)  # message must never surface
        url = str(request.url)
        self.calls.append((request.method, request.url.path))
        if request.url.host == "oauth2.googleapis.com" and request.url.path == "/token":
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": ACCESS})
        if request.headers.get("authorization") not in (f"Bearer {ACCESS}", None):
            return httpx.Response(401, json={"error": {"errors": [{"reason": "authError"}]}})
        if request.method == "POST" and request.url.path == "/upload/drive/v3/files":
            meta = json.loads(request.content)
            if meta["name"] in self.fail_upload_for:
                return httpx.Response(500, json={"error": {"errors": [{"reason": "backendError"}]}})
            self._n += 1
            token = f"sess{self._n}"
            self._pending[token] = meta["name"]
            return httpx.Response(200, headers={"Location": f"https://www.googleapis.com/upload/session/{token}"})
        if request.method == "PUT" and "/upload/session/" in url:
            name = self._pending.pop(url.rsplit("/", 1)[1])
            content = request.read()
            fid = self.seed(name, content)
            return httpx.Response(
                200,
                json={"id": fid, "name": name, "size": str(len(content)), "md5Checksum": hashlib.md5(content).hexdigest()},
            )
        if request.method == "GET" and request.url.path == "/drive/v3/files":
            q = request.url.params["q"]
            if "mimeType" in q:
                return httpx.Response(200, json={"files": [{"id": FOLDER, "name": lib.DEFAULT_FOLDER_NAME}]})
            return httpx.Response(
                200,
                json={
                    "files": [
                        {"id": i, "name": f["name"], "size": str(len(f["content"]))} for i, f in self.files.items()
                    ]
                },
            )
        if request.method == "GET" and request.url.path.startswith("/drive/v3/files/"):
            return httpx.Response(200, content=self.files[request.url.path.rsplit("/", 1)[1]]["content"])
        if request.method == "DELETE":
            self.files.pop(request.url.path.rsplit("/", 1)[1])
            return httpx.Response(204)
        return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})


@pytest.fixture
def drive():
    return FakeDrive()


@pytest.fixture
def client(drive):
    config = lib.DriveConfig("client-id-123456", CLIENT_SECRET, REFRESH, FOLDER)
    return lib.DriveClient(config, http=httpx.Client(transport=httpx.MockTransport(drive.handler)), sleep=lambda s: None)


def run_upload(client, tmp_path, now=NOW):
    return lib.upload_pending(
        client, folder_id=FOLDER, backup_dir=tmp_path, state_path=tmp_path / lib.STATE_FILENAME, now=now
    )


# --- upload -----------------------------------------------------------------


def test_upload_success_sends_dump_and_manifest_and_records_state(drive, client, tmp_path):
    dump = make_backup(tmp_path, NOW - timedelta(minutes=5))
    report = run_upload(client, tmp_path)
    assert report.ok and report.uploaded == [dump.name]
    assert drive.names() == {dump.name, dump.name + ".manifest.json"}
    state = lib.UploadState.load(tmp_path / lib.STATE_FILENAME)
    assert dump.name in state.uploaded and state.last_error is None and state.last_success_at
    assert dump.exists()  # local copy untouched


def test_upload_failure_keeps_local_backup_and_queues_it(drive, client, tmp_path):
    dump = make_backup(tmp_path, NOW - timedelta(minutes=5))
    drive.fail_upload_for = {dump.name}
    report = run_upload(client, tmp_path)
    assert not report.ok and report.failed[0][0] == dump.name
    assert dump.exists() and dump.with_name(dump.name + ".manifest.json").exists()
    state = lib.UploadState.load(tmp_path / lib.STATE_FILENAME)
    assert dump.name not in state.uploaded and state.last_error
    lines, healthy = lib.drive_status(
        secrets_file=_write_secrets(tmp_path), backup_dir=tmp_path, state_path=tmp_path / lib.STATE_FILENAME, now=NOW
    )
    assert not healthy and any("Pending uploads:   1" in line for line in lines)


def test_next_run_retries_queued_backup_and_clears_error(drive, client, tmp_path):
    dump = make_backup(tmp_path, NOW - timedelta(minutes=70))
    drive.fail_upload_for = {dump.name}
    assert not run_upload(client, tmp_path).ok
    drive.fail_upload_for = set()
    newer = make_backup(tmp_path, NOW - timedelta(minutes=5))
    report = run_upload(client, tmp_path)
    assert report.ok and set(report.uploaded) == {dump.name, newer.name}
    assert lib.UploadState.load(tmp_path / lib.STATE_FILENAME).last_error is None


def test_network_down_is_recorded_not_raised_and_local_files_survive(drive, client, tmp_path):
    dump = make_backup(tmp_path, NOW - timedelta(minutes=5))
    drive.offline = True
    report = run_upload(client, tmp_path)
    assert report.fatal and "ConnectError" in report.fatal
    assert dump.exists()
    assert lib.UploadState.load(tmp_path / lib.STATE_FILENAME).last_error


def test_rejected_refresh_token_says_to_rerun_setup(drive, client, tmp_path):
    make_backup(tmp_path, NOW - timedelta(minutes=5))
    drive.token_status = 400
    report = run_upload(client, tmp_path)
    assert report.fatal and "setup" in report.fatal and "7 days" in report.fatal


def test_rerun_is_idempotent_and_does_not_reupload(drive, client, tmp_path):
    make_backup(tmp_path, NOW - timedelta(minutes=5))
    run_upload(client, tmp_path)
    puts = sum(1 for m, _ in drive.calls if m == "PUT")
    (tmp_path / lib.STATE_FILENAME).unlink()  # lost state: healed from the Drive listing
    report = run_upload(client, tmp_path)
    assert report.ok and sum(1 for m, _ in drive.calls if m == "PUT") == puts
    assert len(report.already_present) == 1


def test_half_finished_upload_only_sends_the_missing_manifest(drive, client, tmp_path):
    dump = make_backup(tmp_path, NOW - timedelta(minutes=5))
    drive.seed(dump.name, dump.read_bytes())
    run_upload(client, tmp_path)
    assert drive.names() == {dump.name, dump.name + ".manifest.json"}
    assert sum(1 for m, _ in drive.calls if m == "PUT") == 1


def test_checksum_mismatch_from_drive_deletes_copy_and_fails(drive, client, tmp_path):
    dump = make_backup(tmp_path, NOW - timedelta(minutes=5))
    original = drive.handler

    def lying(request):
        resp = original(request)
        if request.method == "PUT":
            body = json.loads(resp.content)
            body["md5Checksum"] = "0" * 32
            return httpx.Response(200, json=body)
        return resp

    client._http = httpx.Client(transport=httpx.MockTransport(lying))
    report = run_upload(client, tmp_path)
    assert not report.ok and "checksum" in report.failed[0][1]
    assert dump.name not in drive.names()


def test_concurrent_run_is_refused(client, tmp_path):
    make_backup(tmp_path, NOW)
    (tmp_path / lib.LOCK_FILENAME).write_text("123")
    with pytest.raises(lib.DriveBusy):
        run_upload(client, tmp_path)


# --- retention on Drive -----------------------------------------------------


def test_drive_retention_uses_tiered_selection_and_keeps_newest(drive, client, tmp_path):
    ages_hours = [1, 5, 30, 50, 52, 74, 76, 24 * 31, 24 * 40]
    names = []
    for h in ages_hours:
        ts = NOW - timedelta(hours=h)
        n = _name(ts)
        names.append(n)
        drive.seed(n, b"x")
        drive.seed(n + ".manifest.json", b"{}")
    make_backup(tmp_path, NOW - timedelta(minutes=5))
    report = run_upload(client, tmp_path)
    expected = {
        p.name
        for p in lib.select_tiered_prune_candidates(
            [(Path(n), lib.parse_backup_filename(n)[1]) for n in names + [_name(NOW - timedelta(minutes=5))]],
            now=NOW,
        )
    }
    assert expected and set(report.pruned) == expected
    for name in expected:
        assert name not in drive.names() and name + ".manifest.json" not in drive.names()
    assert _name(NOW - timedelta(hours=1)) in drive.names()
    assert _name(NOW - timedelta(minutes=5)) in drive.names()  # newest never deleted


def test_retention_never_deletes_the_only_backup_even_when_ancient(drive, client, tmp_path):
    old = NOW - timedelta(days=90)
    drive.seed(_name(old), b"x")
    drive.seed(_name(old) + ".manifest.json", b"{}")
    report = run_upload(client, tmp_path)
    assert report.pruned == [] and _name(old) in drive.names()


def test_old_queued_backup_outside_retention_is_not_uploaded_just_to_be_deleted(drive, client, tmp_path):
    keep = make_backup(tmp_path, NOW - timedelta(minutes=5))
    # two backups on the same old UTC day: only the day's newest survives retention
    make_backup(tmp_path, NOW - timedelta(hours=100, minutes=0))
    make_backup(tmp_path, NOW - timedelta(hours=101, minutes=0))
    report = run_upload(client, tmp_path)
    assert report.ok and len(report.retired_by_retention) == 1
    assert keep.name in drive.names()


def test_no_prune_when_google_is_unreachable(drive, client, tmp_path):
    n = _name(NOW - timedelta(hours=60))
    drive.seed(n, b"x")
    drive.seed(_name(NOW - timedelta(hours=61)), b"x")
    make_backup(tmp_path, NOW - timedelta(minutes=5))
    drive.offline = True
    report = run_upload(client, tmp_path)
    assert report.pruned == []
    assert len(drive.files) == 2


# --- secrets never leak -----------------------------------------------------


def test_secrets_never_appear_in_errors_state_logs_or_output(drive, client, tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    dump = make_backup(tmp_path, NOW - timedelta(minutes=5))
    drive.offline = True
    report = run_upload(client, tmp_path)
    drive.offline = False
    drive.fail_upload_for = {dump.name}
    report2 = run_upload(client, tmp_path)
    drive.token_status = 400
    client._access_token = None
    report3 = run_upload(client, tmp_path)
    blobs = [
        repr(report),
        repr(report2),
        repr(report3),
        repr(client._config),
        (tmp_path / lib.STATE_FILENAME).read_text(),
        capsys.readouterr().out,
        caplog.text,
    ]
    for blob in blobs:
        for secret in SENTINELS:
            assert secret not in blob


def test_scrub_removes_registered_secrets_and_bearer_tokens():
    lib.register_secret("super-secret-value")
    assert "super-secret-value" not in lib.scrub("x super-secret-value y")
    assert "abc.def" not in lib.scrub("Authorization: Bearer abc.def")
    assert "super-secret-value" not in str(lib.DriveError("failed with super-secret-value"))


def test_secret_file_written_atomically_with_restricted_mode(tmp_path):
    path = tmp_path / "sec" / "drive-oauth.json"
    lib.write_secret_file(path, {"client_id": "a", "client_secret": "b", "refresh_token": "c", "folder_id": "d"})
    if os.name == "posix":
        assert (path.stat().st_mode & 0o777) == 0o600
    assert lib.load_config(path).refresh_token == "c"
    assert not list(path.parent.glob(".tmp-secret-*"))


def test_load_config_error_does_not_echo_file_contents(tmp_path):
    path = tmp_path / "drive-oauth.json"
    path.write_text('{"refresh_token": "' + REFRESH + '"')  # truncated JSON
    with pytest.raises(lib.DriveError) as err:
        lib.load_config(path)
    assert REFRESH not in str(err.value)


# --- setup (device flow) ----------------------------------------------------


def _flow_http(responses):
    seq = iter(responses)

    def handler(request):
        if request.url.path == "/device/code":
            return httpx.Response(
                200,
                json={"device_code": "DEVICE-CODE-SECRET", "user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device", "expires_in": 900, "interval": 1},
            )
        return next(seq)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_device_flow_polls_until_approved_and_prints_only_public_values():
    said = []
    http = _flow_http(
        [
            httpx.Response(428, json={"error": "authorization_pending"}),
            httpx.Response(403, json={"error": "slow_down"}),
            httpx.Response(200, json={"refresh_token": REFRESH, "scope": lib.SCOPE}),
        ]
    )
    token = lib.run_device_flow("cid-123456", CLIENT_SECRET, http=http, say=said.append, sleep=lambda s: None)
    assert token == REFRESH
    text = "\n".join(said)
    assert "ABCD-EFGH" in text and "google.com/device" in text
    assert REFRESH not in text and "DEVICE-CODE-SECRET" not in text and CLIENT_SECRET not in text


@pytest.mark.parametrize("reason,fragment", [("access_denied", "declined"), ("expired_token", "expired")])
def test_device_flow_terminal_errors(reason, fragment):
    http = _flow_http([httpx.Response(400, json={"error": reason})])
    with pytest.raises(lib.DriveError, match=fragment):
        lib.run_device_flow("cid-123456", CLIENT_SECRET, http=http, say=lambda m: None, sleep=lambda s: None)


def test_device_flow_requires_drive_file_scope_only():
    assert lib.SCOPE == "https://www.googleapis.com/auth/drive.file"


# --- status -----------------------------------------------------------------


def _write_secrets(tmp_path) -> Path:
    path = tmp_path / "secrets" / "drive-oauth.json"
    lib.write_secret_file(path, {"client_id": "c", "client_secret": CLIENT_SECRET, "refresh_token": REFRESH, "folder_id": FOLDER})
    return path


def test_status_not_configured(tmp_path):
    lines, healthy = lib.drive_status(secrets_file=tmp_path / "nope.json", backup_dir=tmp_path, state_path=tmp_path / "s.json", now=NOW)
    assert not healthy and "NOT CONFIGURED" in lines[0]


def test_status_ok_after_upload_and_never_prints_secret_values(drive, client, tmp_path):
    make_backup(tmp_path, NOW - timedelta(minutes=5))
    run_upload(client, tmp_path)
    lines, healthy = lib.drive_status(
        secrets_file=_write_secrets(tmp_path), backup_dir=tmp_path, state_path=tmp_path / lib.STATE_FILENAME, now=NOW
    )
    text = "\n".join(lines)
    assert healthy and "Pending uploads:   0" in text and "Last local backup:" in text
    assert not any(s in text for s in SENTINELS)


# --- download / restore-anywhere -------------------------------------------


def test_list_and_download_latest_verifies_checksum(drive, client, tmp_path):
    older = make_backup(tmp_path / "src", NOW - timedelta(hours=3), b"older")
    newer = make_backup(tmp_path / "src", NOW - timedelta(hours=1), b"newer-bytes")
    for dump in (older, newer):
        drive.seed(dump.name, dump.read_bytes())
        drive.seed(dump.name + ".manifest.json", dump.with_name(dump.name + ".manifest.json").read_bytes())
    drive.seed(_name(NOW), b"orphan-without-manifest")
    backups = lib.list_drive_backups(client, FOLDER)
    assert [b.name for b in backups] == [newer.name, older.name]  # orphan excluded
    out = tmp_path / "fresh-pc"
    path = lib.download_backup(client, backups[0], out)
    assert path.read_bytes() == b"newer-bytes" and (out / (newer.name + ".manifest.json")).exists()
    assert not list(out.glob("*.partial"))


def test_download_rejects_corrupt_bytes_and_leaves_no_artifact(drive, client, tmp_path):
    good = make_backup(tmp_path / "src", NOW - timedelta(hours=1), b"good-bytes")
    drive.seed(good.name, b"tampered!!")
    drive.seed(good.name + ".manifest.json", good.with_name(good.name + ".manifest.json").read_bytes())
    backup = lib.list_drive_backups(client, FOLDER)[0]
    out = tmp_path / "fresh-pc"
    with pytest.raises(lib.DriveError, match="checksum"):
        lib.download_backup(client, backup, out)
    assert not (out / good.name).exists() and not list(out.glob("*.partial"))


# --- CLI --------------------------------------------------------------------


def test_cli_upload_without_setup_fails_cleanly(tmp_path, capsys):
    rc = drive_backup.main(["--backup-dir", str(tmp_path), "--secrets-file", str(tmp_path / "missing.json"), "upload"])
    assert rc == 3 and "setup" in capsys.readouterr().err


def test_cli_status_exit_code_reflects_health(tmp_path, capsys):
    rc = drive_backup.main(["--backup-dir", str(tmp_path), "--secrets-file", str(tmp_path / "missing.json"), "status"])
    assert rc == 1 and "NOT CONFIGURED" in capsys.readouterr().out
