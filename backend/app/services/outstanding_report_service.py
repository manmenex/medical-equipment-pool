"""Owner Governance 2026-11-28 (D30): read-only long-outstanding dispatch report.

Open dispatches older than N days, grouped by ward. Age is derived from
``borrowed_at`` at query time; nothing is stored, no due date, no overdue flag,
no notification. HN is never decrypted: ``has_hn`` is only whether the
encrypted column is present.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.equipment import Equipment
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.services.equipment_badge import badge_text
from app.services.system_notes import clean_label

BKK = ZoneInfo("Asia/Bangkok")
NO_WARD = "ไม่ระบุหน่วยงาน"


@dataclass
class OutstandingRow:
    transaction_no: str
    bcm_code: str | None
    equipment_name: str
    category: str | None
    source: str
    source_badge: str | None
    ward: str
    borrowed_at: datetime
    age_days: int
    keyer: str | None
    has_hn: bool


@dataclass
class OutstandingWard:
    ward: str
    rows: list[OutstandingRow] = field(default_factory=list)


async def build_report(db: AsyncSession, days: int, now: datetime | None = None) -> list[OutstandingWard]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    stmt = (
        select(
            BorrowTransaction,
            # D31: hn_recorded (not ciphertext presence) survives retention erasure.
            BorrowTransaction.hn_recorded.label("hn_present"),
            Ward.name,
        )
        .join(Equipment, Equipment.id == BorrowTransaction.equipment_id)
        .outerjoin(Ward, Ward.id == BorrowTransaction.ward_id)
        .options(
            joinedload(BorrowTransaction.equipment).joinedload(Equipment.category),
            joinedload(BorrowTransaction.borrower_user),
        )
        .where(
            BorrowTransaction.status == TransactionStatus.OPEN,
            BorrowTransaction.borrowed_at < cutoff,
            Equipment.returned_to_owner_at.is_(None),
        )
        .order_by(BorrowTransaction.borrowed_at.asc())
    )
    groups: dict[str, OutstandingWard] = {}
    for tx, hn_present, ward_name in (await db.execute(stmt)).unique().all():
        name = ward_name or NO_WARD
        eq = tx.equipment
        borrowed = tx.borrowed_at if tx.borrowed_at.tzinfo else tx.borrowed_at.replace(tzinfo=timezone.utc)
        groups.setdefault(name, OutstandingWard(name)).rows.append(
            OutstandingRow(
                transaction_no=tx.transaction_no,
                bcm_code=eq.bcm_code,
                equipment_name=eq.equipment_name,
                category=eq.category.name if eq.category else None,
                source=eq.equipment_source,
                source_badge=badge_text(eq.equipment_source),
                ward=name,
                borrowed_at=borrowed.astimezone(BKK),
                age_days=(now - borrowed).days,
                keyer=clean_label(tx.dispatch_keyer_label)
                or (tx.borrower_user.full_name if tx.borrower_user else None),
                has_hn=bool(hn_present),
            )
        )
    return [groups[k] for k in sorted(groups)]


def render_line_text(groups: list[OutstandingWard], days: int) -> str:
    total = sum(len(g.rows) for g in groups)
    lines = [f"เครื่องค้างเกิน {days} วัน (รวม {total} เครื่อง)"]
    for g in groups:
        codes = ", ".join(r.bcm_code or "-" for r in g.rows)
        lines.append(f"{g.ward} = {len(g.rows)} เครื่อง: {codes}")
    return "\n".join(lines)
