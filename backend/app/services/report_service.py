import csv
import io

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transaction import BorrowTransaction

REPORT_COLUMNS = [
    "transaction_no",
    "asset_number",
    "equipment_name",
    "borrower_name",
    "borrowed_at",
    "due_at",
    "returned_at",
    "status",
    "condition_on_return",
]


async def _fetch_rows(db: AsyncSession) -> list[list[str]]:
    stmt = (
        select(BorrowTransaction)
        .options(selectinload(BorrowTransaction.equipment))
        .order_by(BorrowTransaction.borrowed_at.desc())
        .limit(50000)
    )
    txs = (await db.execute(stmt)).scalars().all()
    rows = []
    for tx in txs:
        rows.append(
            [
                tx.transaction_no,
                tx.equipment.asset_number if tx.equipment else "",
                tx.equipment.equipment_name if tx.equipment else "",
                tx.borrower_name,
                tx.borrowed_at.isoformat() if tx.borrowed_at else "",
                tx.due_at.isoformat() if tx.due_at else "",
                tx.returned_at.isoformat() if tx.returned_at else "",
                tx.status,
                tx.condition_on_return or "",
            ]
        )
    return rows


async def export_csv(db: AsyncSession) -> bytes:
    rows = await _fetch_rows(db)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(REPORT_COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


async def export_xlsx(db: AsyncSession) -> bytes:
    rows = await _fetch_rows(db)
    wb = Workbook()
    ws = wb.active
    ws.title = "Borrow Report"
    ws.append(REPORT_COLUMNS)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
