"""One sync pass: sheet rows -> sync-ledger client operations.

Every row becomes a ``SyncOperation`` that goes through
``sync_service.process_operation`` -- the exact engine behind
``POST /sync/operations`` -- so dispatch/receipt services own the lifecycle,
a re-run is a no-op (deterministic ``op_id`` + ledger idempotency) and any
lifecycle conflict lands in the existing review page. This module never
touches equipment or transaction state directly and never writes to the
sheet.

Not imported: free-text notes, ward-side person names, anything that looks
like a patient number (see ``sheet_parser``).
"""
import hashlib
import logging
import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import client_operation as client_op_crud
from app.crud import equipment as equipment_crud
from app.crud import transaction as transaction_crud
from app.models.client_operation import OP_STATUS_APPLIED, OP_STATUS_PENDING, OP_STATUS_RESOLVED
from app.models.master_data import Ward
from app.models.transaction import DispatchType, ReceiptOutcome
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, Role, User
from app.schemas.sync import OP_TYPE_DISPATCH, OP_TYPE_RECEIPT, SyncOperation, SyncReceiptBody
from app.schemas.transaction import BorrowRequest
from app.services import sync_service
from app.services.legacy_sheet_sync.config import SyncConfig, SyncConfigError
from app.services.legacy_sheet_sync.sheet_parser import (
    KIND_DISPATCH,
    KIND_RECEIPT,
    LegacyRow,
    SkippedRow,
    parse_tab,
    tab_title,
)
from app.services.legacy_sheet_sync.sheets_client import SheetReader

logger = logging.getLogger("legacy_sheet_sync")

# Fixed, valid UUID v4 (the envelope only accepts v4 ids).
DEVICE_ID = uuid.UUID("a6c1f2d4-5b3e-4c7a-9d10-6e2f8b4a1c35")
_OP_NAMESPACE = uuid.UUID("3f0c8a52-6d1e-5b7a-8c44-1d2e3f4a5b6c")
USER_AGENT = "legacy-sheet-sync"
NOTE_MAX = 300


def op_id_for(kind: str, row_id: str) -> uuid.UUID:
    """uuid5(namespace, 'legacy-sheet:<tab>:<row id>') with the version bits
    set to 4, because the sync envelope rejects any other UUID version."""
    return uuid.UUID(bytes=uuid.uuid5(_OP_NAMESPACE, f"legacy-sheet:{kind}:{row_id.lower()}").bytes, version=4)


def device_seq_for(kind: str, row: LegacyRow) -> int:
    """Stable, increasing-by-time and unique per (tab, row id).

    (minute-of-event * 2 + tab) * 2^32 + 32-bit hash of the row id. Depends
    only on row content, never on the row's position, so inserting rows in
    the sheet cannot shift it. UNIQUE(device_id, device_seq) is respected
    because the row id is unique per tab. Bounded well below 2**62."""
    minute = int(row.occurred_at.timestamp() // 60)
    tab_bit = 0 if kind == KIND_DISPATCH else 1
    h = int.from_bytes(hashlib.sha256(row.row_id.encode()).digest()[:4], "big")
    return ((minute * 2 + tab_bit) << 32) + h


def _ward_key(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s\-_./()]+", "", t)


def bcm_candidates(raw: str) -> list[str]:
    s = re.sub(r"\s+", "", raw.strip().upper())
    out: list[str] = []
    if s.isdigit():
        out.append("BCM" + s)
    else:
        out.append(s)
        if not s.startswith("BCM"):
            out.append("BCM" + s)
    return list(dict.fromkeys(out))


def _eq_key(raw: str) -> str:
    return bcm_candidates(raw)[0]


def build_note(row: LegacyRow) -> str:
    parts = [f"legacy sheet {row.kind} row {row.row_id}"]
    if row.doc_no:
        parts.append(row.doc_no)
    if row.bme_name:
        parts.append(f"BME {row.bme_name}")
    if row.failed_accessories:
        parts.append("accessories: " + ", ".join(f"{a} ✗" for a in row.failed_accessories))
    return "; ".join(parts)[:NOTE_MAX]


@dataclass
class RunReport:
    dry_run: bool = False
    counts: Counter = field(default_factory=Counter)
    skipped: list[dict] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)

    def skip(self, kind: str, row_id: str, reason: str) -> None:
        self.counts["skipped"] += 1
        self.skipped.append({"tab": kind, "row_id": row_id, "reason": reason})

    def summary(self) -> str:
        body = " ".join(f"{k}={v}" for k, v in sorted(self.counts.items())) or "nothing to do"
        return f"legacy_sheet_sync {'DRY-RUN ' if self.dry_run else ''}pass: {body}"


async def _load_sync_user(db: AsyncSession, employee_code: str) -> User:
    user = (await db.execute(select(User).where(User.employee_code == employee_code))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise SyncConfigError(
            f"Sync operator user '{employee_code}' does not exist or is inactive. "
            "Create it (Equipment Pool Staff role) in the admin UI first."
        )
    role = await db.get(Role, user.role_id)
    if role is None or role.name not in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF):
        raise SyncConfigError(f"Sync operator user '{employee_code}' must be Equipment Pool Staff.")
    return user


class _Resolver:
    def __init__(self, db: AsyncSession, wards: list[Ward]):
        self._db = db
        self._by_name: dict[str, list[Ward]] = defaultdict(list)
        for w in wards:
            self._by_name[_ward_key(w.name)].append(w)
            self._by_name[_ward_key(w.code)].append(w)
        self._eq: dict[str, object] = {}

    def ward(self, raw: str) -> tuple[Ward | None, str | None]:
        found = {w.id: w for w in self._by_name.get(_ward_key(raw), [])}
        if len(found) == 1:
            return next(iter(found.values())), None
        return None, ("ambiguous_ward" if found else "unknown_ward")

    async def equipment(self, raw: str):
        key = _eq_key(raw)
        if key not in self._eq:
            cands = bcm_candidates(raw)
            hits = await equipment_crud.get_by_bcm_codes(self._db, cands)
            self._eq[key] = next(iter(hits.values())) if len(hits) == 1 else (None if not hits else "ambiguous")
        val = self._eq[key]
        if val is None:
            return None, "unknown_bcm"
        if val == "ambiguous":
            return None, "ambiguous_bcm"
        return val, None


def _envelope(row: LegacyRow, user: User, *, dispatch=None, receipt=None) -> SyncOperation:
    return SyncOperation(
        op_id=op_id_for(row.kind, row.row_id),
        device_id=DEVICE_ID,
        device_seq=device_seq_for(row.kind, row),
        user_id=user.id,
        op_type=OP_TYPE_DISPATCH if row.kind == KIND_DISPATCH else OP_TYPE_RECEIPT,
        occurred_at_local=row.occurred_at,
        clock_offset_ms=0,
        dispatch=dispatch,
        receipt=receipt,
    )


async def _submit(db: AsyncSession, op: SyncOperation, user: User, row: LegacyRow, report: RunReport) -> None:
    try:
        res = await sync_service.process_operation(db, op, user, user_agent=USER_AGENT)
    except Exception as exc:  # one bad row must not stop the pass
        await db.rollback()
        report.counts["error"] += 1
        report.skipped.append({"tab": row.kind, "row_id": row.row_id, "reason": f"error:{type(exc).__name__}"})
        logger.warning("legacy_sheet_sync row error tab=%s row=%s type=%s", row.kind, row.row_id, type(exc).__name__)
        return
    report.counts[res.result] += 1
    if res.result in ("conflict", "rejected", "retry_later"):
        report.review.append({"tab": row.kind, "row_id": row.row_id, "result": res.result, "code": res.code})


async def run_once(session_factory, reader: SheetReader, cfg: SyncConfig, *, dry_run: bool = False,
                   now: datetime | None = None) -> RunReport:
    report = RunReport(dry_run=dry_run)
    parsed = {}
    for kind in (KIND_DISPATCH, KIND_RECEIPT):
        parsed[kind] = parse_tab(kind, await reader.read_tab(tab_title(kind)))
        report.counts[f"read_{kind}"] = len(parsed[kind].rows)
        for s in parsed[kind].skipped:
            _record_parse_skip(report, s)

    start = cfg.backfill_start(now)
    events: list[LegacyRow] = []
    for kind in (KIND_DISPATCH, KIND_RECEIPT):
        for r in parsed[kind].rows:
            if r.occurred_at < start:
                report.counts["before_start"] += 1
            else:
                events.append(r)
    # Chronological; at the same instant a dispatch precedes a receipt.
    events.sort(key=lambda r: (r.occurred_at, 0 if r.kind == KIND_DISPATCH else 1, r.row_id))

    dispatches_by_eq: dict[str, list[LegacyRow]] = defaultdict(list)
    for r in parsed[KIND_DISPATCH].rows:
        dispatches_by_eq[_eq_key(r.bcm_raw)].append(r)
    for lst in dispatches_by_eq.values():
        lst.sort(key=lambda r: r.occurred_at)

    skipped_dispatch_ids: set[str] = set()
    async with session_factory() as db:
        user = await _load_sync_user(db, cfg.employee_code)
        wards = list((await db.execute(select(Ward))).scalars().all())
        resolver = _Resolver(db, wards)
        for row in events:
            op_id = op_id_for(row.kind, row.row_id)
            existing = await client_op_crud.get(db, op_id)
            if existing is not None and existing.status != OP_STATUS_PENDING:
                report.counts[f"already_{existing.status}"] += 1
                continue
            ward, werr = resolver.ward(row.ward_raw)
            eq, eerr = await resolver.equipment(row.bcm_raw)
            if row.kind == KIND_DISPATCH:
                if werr or eerr:
                    skipped_dispatch_ids.add(row.row_id)
                    report.skip(row.kind, row.row_id, f"{werr or eerr}: {(row.ward_raw if werr else row.bcm_raw)[:40]}")
                    continue
                if dry_run:
                    report.counts["would_apply"] += 1
                    report.planned.append(f"dispatch {row.row_id} {eq.bcm_code} -> {ward.name}")
                    continue
                body = BorrowRequest(
                    equipment_id=str(eq.id), ward_id=str(ward.id),
                    dispatch_type=DispatchType.ON_DEMAND, notes=build_note(row),
                )
                await _submit(db, _envelope(row, user, dispatch=body), user, row, report)
                continue
            # receipt
            if eerr:
                report.skip(row.kind, row.row_id, f"{eerr}: {row.bcm_raw[:40]}")
                continue
            tx_id, why = await _receipt_target(db, row, eq, dispatches_by_eq, skipped_dispatch_ids, dry_run, start)
            if why:
                report.skip(row.kind, row.row_id, why)
                continue
            if dry_run:
                report.counts["would_apply"] += 1
                report.planned.append(f"receipt {row.row_id} {eq.bcm_code}")
                continue
            body = SyncReceiptBody(transaction_id=tx_id, receipt_outcome=ReceiptOutcome.USABLE, notes=build_note(row))
            await _submit(db, _envelope(row, user, receipt=body), user, row, report)
    logger.info(report.summary())
    return report


def _record_parse_skip(report: RunReport, s: SkippedRow) -> None:
    report.skip(s.kind, s.row_id, s.reason)


async def _receipt_target(db, row, eq, dispatches_by_eq, skipped_dispatch_ids, dry_run, start):
    """Which transaction does this return close? Returns (tx_id, skip_reason).

    1. The latest sheet dispatch for the same equipment at or before the
       return: if it was applied by this sync, its transaction (a dispatch's
       transaction id equals its op_id).
    2. Otherwise (dispatch predates the backfill window or never came from
       the sheet): the equipment's current open transaction."""
    matched = None
    for d in dispatches_by_eq.get(_eq_key(row.bcm_raw), []):
        if d.occurred_at <= row.occurred_at:
            matched = d
    if matched is not None and matched.row_id in skipped_dispatch_ids:
        return None, "matching_dispatch_skipped"
    if matched is not None:
        led = await client_op_crud.get(db, op_id_for(KIND_DISPATCH, matched.row_id))
        if led is not None:
            if led.status in (OP_STATUS_APPLIED, OP_STATUS_RESOLVED) and led.transaction_id:
                return led.transaction_id, None
            return None, "matching_dispatch_in_review"
        if dry_run and matched.occurred_at >= start:
            return op_id_for(KIND_DISPATCH, matched.row_id), None  # would exist after the dispatch applies
    open_tx = await transaction_crud.get_open_transaction_for_equipment(db, eq.id)
    if open_tx is None:
        return None, "no_open_transaction"
    return open_tx.id, None
