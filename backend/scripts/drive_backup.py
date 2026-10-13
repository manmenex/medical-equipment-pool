#!/usr/bin/env python3
"""PR25A: off-host backup to Google Drive (operator CLI).

Runs INSIDE the backend container, driven by deployment/local-staging/
drive-backup.ps1 and backup.ps1, with the backup directory and a secrets
directory bind-mounted. See drive_backup_lib.py for the design.

Commands:
    setup      one-time OAuth consent (device flow); writes the secret file
    upload     upload pending backups, apply Drive retention
    status     offline: last local backup, last upload, pending count
    list       backups available on Drive
    download   fetch a backup from Drive (--latest or --name) and verify it

Exit codes: 0 ok; 1 error/attention; 3 some uploads failed and are queued
for the next run (the local backups are untouched either way).

No token, client secret or refresh token is ever printed or logged.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from scripts.drive_backup_lib import (  # noqa: E402
    DEFAULT_FOLDER_NAME,
    SECRETS_FILENAME,
    STATE_FILENAME,
    DriveBusy,
    DriveClient,
    DriveConfig,
    DriveError,
    download_backup,
    drive_status,
    list_drive_backups,
    load_config,
    register_secret,
    run_device_flow,
    scrub,
    upload_pending,
    write_secret_file,
)
from scripts.pg_backup_lib import default_backup_dir  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backup-dir", default=os.environ.get("BACKUP_OUTPUT_DIR"))
    parser.add_argument(
        "--secrets-file",
        default=os.environ.get("MEP_DRIVE_SECRETS_FILE", f"/mep-drive-secrets/{SECRETS_FILENAME}"),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup")
    setup.add_argument("--folder-name", default=DEFAULT_FOLDER_NAME)
    sub.add_parser("upload")
    sub.add_parser("status")
    sub.add_parser("list")
    download = sub.add_parser("download")
    group = download.add_mutually_exclusive_group(required=True)
    group.add_argument("--latest", action="store_true")
    group.add_argument("--name", help="Exact mep-postgres-<env>-<timestamp>.dump name from `list`")
    return parser.parse_args(argv)


def _backup_dir(args: argparse.Namespace) -> Path:
    return Path(args.backup_dir) if args.backup_dir else default_backup_dir()


def _client(args: argparse.Namespace) -> tuple[DriveClient, DriveConfig]:
    config = load_config(Path(args.secrets_file))
    return DriveClient(config), config


def cmd_setup(args: argparse.Namespace) -> int:
    secrets_file = Path(args.secrets_file)
    client_id = os.environ.get("MEP_DRIVE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("MEP_DRIVE_CLIENT_SECRET", "").strip()
    if not (client_id and client_secret) and secrets_file.is_file():
        try:
            existing = load_config(secrets_file)
            client_id, client_secret = existing.client_id, existing.client_secret
        except DriveError:
            pass
    if not (client_id and client_secret):
        print("[drive] FAIL: no OAuth client ID/secret supplied (MEP_DRIVE_CLIENT_ID / MEP_DRIVE_CLIENT_SECRET)", file=sys.stderr)
        return 1
    register_secret(client_id)
    register_secret(client_secret)

    with httpx.Client(timeout=30.0) as http:
        refresh_token = run_device_flow(client_id, client_secret, http=http, say=lambda m: print(f"[drive] {m}", flush=True))
        placeholder = DriveConfig(client_id, client_secret, refresh_token, folder_id="pending", folder_name=args.folder_name)
        folder_id = DriveClient(placeholder, http=http).find_or_create_folder(args.folder_name)
        config = DriveConfig(client_id, client_secret, refresh_token, folder_id, args.folder_name)
        DriveClient(config, http=http).list_folder(folder_id)  # prove the whole path works before saving
    write_secret_file(
        secrets_file,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "folder_id": folder_id,
            "folder_name": args.folder_name,
        },
    )
    print(f"[drive] OK: setup complete; backups will go to the Drive folder '{args.folder_name}'")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    backup_dir = _backup_dir(args)
    client, config = _client(args)
    report = upload_pending(
        client, folder_id=config.folder_id, backup_dir=backup_dir, state_path=backup_dir / STATE_FILENAME
    )
    for name in report.uploaded:
        print(f"[drive] uploaded: {name}")
    for name in report.already_present:
        print(f"[drive] already on Drive: {name}")
    for name in report.retired_by_retention:
        print(f"[drive] skipped (outside Drive retention): {name}")
    for name in report.pruned:
        print(f"[drive] pruned from Drive: {name}")
    if report.prune_error:
        print(f"[drive] WARNING: Drive retention incomplete: {report.prune_error}")
    if report.fatal:
        print(f"[drive] FAIL: {report.fatal}", file=sys.stderr)
        print("[drive] local backups are untouched; pending uploads retry on the next run", file=sys.stderr)
        return 3
    for name, message in report.failed:
        print(f"[drive] FAIL: {name}: {message}", file=sys.stderr)
    if report.failed:
        print("[drive] local backups are untouched; failed uploads retry on the next run", file=sys.stderr)
        return 3
    print("[drive] OK: Drive is up to date")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    backup_dir = _backup_dir(args)
    lines, healthy = drive_status(
        secrets_file=Path(args.secrets_file), backup_dir=backup_dir, state_path=backup_dir / STATE_FILENAME
    )
    print("\n".join(lines))
    return 0 if healthy else 1


def cmd_list(args: argparse.Namespace) -> int:
    client, config = _client(args)
    backups = list_drive_backups(client, config.folder_id)
    if not backups:
        print("[drive] no complete backups found on Drive")
        return 1
    for b in backups:
        print(f"{b.name}  {b.created_at:%Y-%m-%d %H:%M}Z  {b.size / 1_000_000:.1f} MB")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    client, config = _client(args)
    backups = list_drive_backups(client, config.folder_id)
    if not backups:
        print("[drive] FAIL: no complete backups found on Drive", file=sys.stderr)
        return 1
    chosen = backups[0] if args.latest else next((b for b in backups if b.name == args.name), None)
    if chosen is None:
        print(f"[drive] FAIL: {args.name} is not on Drive (run `list`)", file=sys.stderr)
        return 1
    path = download_backup(client, chosen, _backup_dir(args))
    # Same line shape as backup_postgres.py so wrappers can bind to the exact artifact.
    print(f"[drive] OK: {path}")
    return 0


COMMANDS = {"setup": cmd_setup, "upload": cmd_upload, "status": cmd_status, "list": cmd_list, "download": cmd_download}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except DriveBusy as exc:
        print(f"[drive] skipped: {exc}")
        return 0
    except DriveError as exc:
        print(f"[drive] FAIL: {scrub(str(exc))}", file=sys.stderr)
        return 3 if args.command == "upload" else 1


if __name__ == "__main__":
    sys.exit(main())
