import csv
import io
import uuid
from datetime import date, datetime, time, timedelta, timezone

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.equipment import Equipment
from app.models.master_data import EquipmentCategory, Ward
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.schemas.checklist import report_columns
from app.services.system_notes import clean_label
from app.utils.bkk_time import BKK, to_bkk

# Owner-usable export (reports-usable). Thai headers, in this order. HN is
# deliberately absent: a patient HN never appears in any export.
REPORT_COLUMNS = [
    "เลขที่รายการ",
    "วันที่จ่าย",
    "เวลาจ่าย",
    "รหัส BCM",
    "ประเภท",
    "ชื่อเครื่อง",
    "แหล่งที่มา",
    "Ward",
    "BME ผู้จ่าย",
    "ผู้รับ (Ward)",
    "วันที่รับคืน",
    "เวลารับคืน",
    "BME ผู้รับคืน",
    "ผู้ส่งคืน (Ward)",
    "สถานะ",
    "สภาพตอนคืน",
    "ตรวจตอนจ่าย",
    "ตรวจตอนคืน",
]

MAX_ROWS = 50000
_SOURCE_LABELS = {"pool": "Pool", "demo": "Demo", "loan": "ยืม"}
_STATUS_LABELS = {
    TransactionStatus.OPEN: "ยังไม่รับคืน",
    TransactionStatus.CLOSED: "รับคืนแล้ว",
    TransactionStatus.VOIDED: "ยกเลิก",
}
_OUTCOME_LABELS = {"usable": "ใช้งานได้", "defective": "ชำรุด"}


def _date(dt: datetime | None) -> str:
    local = to_bkk(dt)
    return local.strftime("%d/%m/%Y") if local else ""


def _time(dt: datetime | None) -> str:
    local = to_bkk(dt)
    return local.strftime("%H:%M") if local else ""


def _mark(value: bool | None) -> str:
    return "-" if value is None else ("✓" if value else "✗")


def _checks(stored: dict | None) -> str:
    try:
        cols = report_columns(stored)
    except Exception:  # malformed stored JSON must not break an export
        cols = {"screen": None, "charger": None, "clamp": None}
    if all(v is None for v in cols.values()):
        return "-"
    return "/".join(_mark(cols[k]) for k in ("screen", "charger", "clamp"))


def _bkk_day_bounds(date_from: date | None, date_to: date | None) -> tuple[datetime | None, datetime | None]:
    """Bangkok calendar days -> UTC-aware [start, end) bounds on borrowed_at."""
    start = datetime.combine(date_from, time.min, tzinfo=BKK).astimezone(timezone.utc) if date_from else None
    end = (
        datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=BKK).astimezone(timezone.utc)
        if date_to and date_to < date.max
        else None
    )
    return start, end


async def _fetch_rows(
    db: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: uuid.UUID | None = None,
) -> list[list[str]]:
    stmt = (
        select(BorrowTransaction)
        .options(
            selectinload(BorrowTransaction.equipment),
            selectinload(BorrowTransaction.borrower_user),
            selectinload(BorrowTransaction.received_by_user),
        )
        .where(BorrowTransaction.status != TransactionStatus.VOIDED)
        .order_by(BorrowTransaction.borrowed_at.desc())
        .limit(MAX_ROWS)
    )
    start, end = _bkk_day_bounds(date_from, date_to)
    if start is not None:
        stmt = stmt.where(BorrowTransaction.borrowed_at >= start)
    if end is not None:
        stmt = stmt.where(BorrowTransaction.borrowed_at < end)
    if category_id is not None:
        stmt = stmt.where(
            BorrowTransaction.equipment_id.in_(select(Equipment.id).where(Equipment.category_id == category_id))
        )
    txs = (await db.execute(stmt)).scalars().all()
    ward_names = {w.id: w.name for w in (await db.execute(select(Ward))).scalars().all()}
    category_names = {c.id: c.name for c in (await db.execute(select(EquipmentCategory))).scalars().all()}
    rows = []
    for tx in txs:
        eq = tx.equipment
        rows.append(
            [
                tx.transaction_no,
                _date(tx.borrowed_at),
                _time(tx.borrowed_at),
                (eq.bcm_code or eq.asset_number or "") if eq else "",
                category_names.get(eq.category_id, "") if eq and eq.category_id else "",
                eq.equipment_name if eq else "",
                _SOURCE_LABELS.get(eq.equipment_source, "Pool") if eq else "",
                ward_names.get(tx.ward_id, "") if tx.ward_id else "",
                clean_label(tx.dispatch_keyer_label)
                or clean_label(tx.borrower_user.full_name if tx.borrower_user else None)
                or "",
                clean_label(tx.dispatch_contact_name) or "",
                _date(tx.returned_at),
                _time(tx.returned_at),
                (
                    clean_label(tx.receipt_keyer_label)
                    or clean_label(tx.received_by_user.full_name if tx.received_by_user else None)
                    or ""
                )
                if tx.returned_at
                else "",
                clean_label(tx.receipt_contact_name) or "",
                # Roadmap PR7: tx.status is a TransactionStatus(str, Enum); a
                # Thai label avoids openpyxl str()-ing the enum member.
                _STATUS_LABELS.get(tx.status, tx.status.value),
                _OUTCOME_LABELS.get(
                    getattr(tx.receipt_outcome, "value", tx.receipt_outcome) or "", tx.condition_on_return or ""
                ),
                _checks(tx.dispatch_checks),
                _checks(tx.receipt_checks) if tx.returned_at else "",
            ]
        )
    return rows


async def export_csv(db: AsyncSession, **filters) -> bytes:
    rows = await _fetch_rows(db, **filters)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(REPORT_COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


async def export_xlsx(db: AsyncSession, **filters) -> bytes:
    rows = await _fetch_rows(db, **filters)
    wb = Workbook()
    ws = wb.active
    ws.title = "Borrow Report"
    ws.append(REPORT_COLUMNS)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
