"""One-off, idempotent admin tool: backfill BME keyer labels (D22) for rows
the Legacy Sheet Sync created before the label column was filled.

    python -m app.scripts.backfill_keyer_labels            # dry-run (default)
    python -m app.scripts.backfill_keyer_labels --apply    # write
    python -m app.scripts.backfill_keyer_labels --repair            # dry-run repair
    python -m app.scripts.backfill_keyer_labels --repair --apply    # write repair

``--repair`` finds keyer labels / contact names that contain sheet-sync trace
text ("legacy sheet ...") and rewrites a keyer label from the trace note's
"BME <name>" part when parseable, else clears it to NULL. Counts only.

Parses the BME name from the internal sheet-sync trace note
("legacy sheet <dispatch|receipt> row ...; BME <name>; ...") and sets
``dispatch_keyer_label`` / ``receipt_keyer_label`` ONLY where it is NULL and
ONLY on transactions the LEGACY-SYNC user created (dispatch: borrower; receipt:
receiver). A dispatch note that a later receipt overwrote cannot be
recovered and is left alone. Existing labels are never overwritten.

Prints COUNTS only -- never a name or any value. ``--apply`` writes in one
transaction together with one summary audit entry (count only).
"""
import argparse
import asyncio
import os
import re

from sqlalchemy import and_, or_, select

from app.crud import audit as audit_crud
from app.db.session import AsyncSessionLocal
from app.models.transaction import BorrowTransaction
from app.models.user import User
from app.services.legacy_sheet_sync.config import DEFAULT_EMPLOYEE_CODE, ENV_EMPLOYEE_CODE
from app.services.system_notes import SYSTEM_NOTE_PREFIX, clean_label, has_system_text, is_system_note

LABEL_MAX = 100
AUDIT_ACTION = "KEYER_LABEL_BACKFILL"
_KIND_RE = re.compile(r"^\s*" + re.escape(SYSTEM_NOTE_PREFIX) + r"(dispatch|receipt) row\b", re.IGNORECASE)


def parse_bme(note: str | None) -> tuple[str, str] | None:
    """(kind, bme name) from a sync trace note, or None."""
    if not note:
        return None
    note = note.strip().splitlines()[0]  # later lines are appended "[Return] ..." traces
    m = _KIND_RE.match(note)
    if not m:
        return None
    for part in note.split("; ")[1:]:
        if part.startswith("BME "):
            name = (clean_label(part[4:]) or "")[:LABEL_MAX]
            return (m.group(1).lower(), name) if name and not is_system_note(name) else None
    return None


async def repair(*, apply: bool, employee_code: str | None = None) -> dict[str, int]:
    """Clear/rewrite labels that hold system-note text, on LEGACY-SYNC rows only
    (borrower for dispatch columns, receiver for receipt columns). Dry-run by default."""
    code = employee_code or (os.environ.get(ENV_EMPLOYEE_CODE) or "").strip() or DEFAULT_EMPLOYEE_CODE
    counts = {"scanned": 0, "rewritten": 0, "cleared": 0}
    pat = f"%{SYSTEM_NOTE_PREFIX}%"
    cols = ("dispatch_keyer_label", "receipt_keyer_label", "dispatch_contact_name", "receipt_contact_name")
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.employee_code == code))).scalar_one_or_none()
        if user is None:
            raise SystemExit("Sync operator user not found. Nothing was changed.")
        owner_col = {"dispatch": BorrowTransaction.borrower_user_id, "receipt": BorrowTransaction.received_by_user_id}
        txs = (
            await db.execute(
                select(BorrowTransaction).where(
                    or_(*(and_(or_(getattr(BorrowTransaction, c).ilike(pat),
                               getattr(BorrowTransaction, c).contains("\n")), owner_col[c.split("_")[0]] == user.id)
                          for c in cols))
                )
            )
        ).scalars().all()
        for tx in txs:
            counts["scanned"] += 1
            for c in cols:
                owner = tx.borrower_user_id if c.startswith("dispatch") else tx.received_by_user_id
                val = getattr(tx, c)
                if owner != user.id or not has_system_text(val):
                    continue
                new = clean_label(val)  # a name with a trace line appended keeps the name
                if new is None and c.endswith("keyer_label"):
                    parsed = parse_bme(getattr(tx, c))
                    if parsed and parsed[0] == c.split("_")[0]:
                        new = parsed[1]
                setattr(tx, c, new)
                counts["rewritten" if new else "cleared"] += 1
        changed = counts["rewritten"] + counts["cleared"]
        if apply and changed:
            await audit_crud.create(
                db, user_id=None, action=AUDIT_ACTION + "_REPAIR", entity_type="borrow_transaction",
                entity_id=None, after_data={"rewritten": counts["rewritten"], "cleared": counts["cleared"]},
            )
            await db.commit()
        else:
            await db.rollback()
    return counts


async def backfill(*, apply: bool, employee_code: str | None = None) -> dict[str, int]:
    code = employee_code or (os.environ.get(ENV_EMPLOYEE_CODE) or "").strip() or DEFAULT_EMPLOYEE_CODE
    counts = {"scanned": 0, "dispatch_labels": 0, "receipt_labels": 0, "skipped": 0}
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.employee_code == code))).scalar_one_or_none()
        if user is None:
            raise SystemExit("Sync operator user not found. Nothing was changed.")
        txs = (
            await db.execute(
                select(BorrowTransaction).where(
                    BorrowTransaction.notes.is_not(None),
                    BorrowTransaction.notes.ilike(f"{SYSTEM_NOTE_PREFIX}%"),
                    or_(
                        and_(
                            BorrowTransaction.borrower_user_id == user.id,
                            BorrowTransaction.dispatch_keyer_label.is_(None),
                        ),
                        and_(
                            BorrowTransaction.received_by_user_id == user.id,
                            BorrowTransaction.receipt_keyer_label.is_(None),
                        ),
                    ),
                )
            )
        ).scalars().all()
        for tx in txs:
            counts["scanned"] += 1
            parsed = parse_bme(tx.notes)
            if parsed is None:
                counts["skipped"] += 1
                continue
            kind, name = parsed
            if kind == "dispatch" and tx.borrower_user_id == user.id and tx.dispatch_keyer_label is None:
                tx.dispatch_keyer_label = name
                counts["dispatch_labels"] += 1
            elif kind == "receipt" and tx.received_by_user_id == user.id and tx.receipt_keyer_label is None:
                tx.receipt_keyer_label = name
                counts["receipt_labels"] += 1
            else:
                counts["skipped"] += 1
        updated = counts["dispatch_labels"] + counts["receipt_labels"]
        if apply and updated:
            await audit_crud.create(
                db,
                user_id=None,
                action=AUDIT_ACTION,
                entity_type="borrow_transaction",
                entity_id=None,
                after_data={"dispatch_labels": counts["dispatch_labels"], "receipt_labels": counts["receipt_labels"]},
            )
            await db.commit()
        else:
            await db.rollback()
    return counts


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--repair", action="store_true", help="repair labels containing system-note text")
    args = parser.parse_args()
    if args.repair:
        r = await repair(apply=args.apply)
        print(f"{'APPLY' if args.apply else 'DRY-RUN'} repair: scanned={r['scanned']} "
              f"rewritten={r['rewritten']} cleared={r['cleared']}")
        if not args.apply:
            print("Nothing written. Re-run with --repair --apply to write.")
        return
    c = await backfill(apply=args.apply)
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: scanned={c['scanned']} "
          f"dispatch_labels={c['dispatch_labels']} receipt_labels={c['receipt_labels']} "
          f"skipped={c['skipped']}")
    if not args.apply:
        print("Nothing written. Re-run with --apply to write.")


if __name__ == "__main__":
    asyncio.run(main())
