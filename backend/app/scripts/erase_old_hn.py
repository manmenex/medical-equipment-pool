"""Admin tool (D31): erase HN older than 2 years (from borrowed_at).

    python -m app.scripts.erase_old_hn            # dry-run (default), count only
    python -m app.scripts.erase_old_hn --apply    # erase + one count-only audit entry

Prints counts only, never a value. Also run daily by the scheduler.
"""
import argparse
import asyncio

from app.db.session import AsyncSessionLocal
from app.services.hn_retention_service import erase_old_hn


async def main(apply: bool) -> int:
    async with AsyncSessionLocal() as db:
        return await erase_old_hn(db, apply=apply)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write (default is a dry-run)")
    a = ap.parse_args()
    n = asyncio.run(main(a.apply))
    print(f"{'erased' if a.apply else 'would erase'}: {n}")
