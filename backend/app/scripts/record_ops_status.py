"""Host-side status report for operations jobs (no data values).

Run inside the backend container by the monthly restore drill:

    python -m app.scripts.record_ops_status --code restore_drill --status fail|pass --detail "<short>"

pass clears the admin alert and stamps the last pass; fail raises it. Stored in
system_heartbeats (key + time only). --detail is validated (short, single line)
and echoed to stdout for the host log; it is not stored.
"""
import argparse
import asyncio

from app.db.session import AsyncSessionLocal
from app.services import health_alert_service

CODES = {"restore_drill"}
MAX_DETAIL = 200


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--code", required=True, choices=sorted(CODES))
    parser.add_argument("--status", required=True, choices=["pass", "fail"])
    parser.add_argument("--detail", default="")
    args = parser.parse_args(argv)
    if len(args.detail) > MAX_DETAIL or "\n" in args.detail or "\r" in args.detail:
        parser.error(f"--detail must be a single line of at most {MAX_DETAIL} characters")
    return args


async def record(db, code: str, status: str) -> None:
    if code == "restore_drill":
        await health_alert_service.record_restore_drill(db, status)
    else:  # pragma: no cover - argparse restricts choices
        raise ValueError(code)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    async with AsyncSessionLocal() as db:
        await record(db, args.code, args.status)
    print(f"recorded {args.code}={args.status} {args.detail}".rstrip())


if __name__ == "__main__":
    asyncio.run(main())
