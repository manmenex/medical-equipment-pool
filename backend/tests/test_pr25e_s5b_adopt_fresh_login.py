"""Roadmap PR25E slice S5b: server-side fresh-login rule for adoption
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 8.3, Owner decision D4)
plus two review follow-up tests for adoption."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.export import ExportEvent
from app.models.transaction import BorrowTransaction
from tests.test_pr25e_b2_sync_ops import _send, _user, ctx, dispatch_op, receipt_op  # noqa: F401

pytestmark = pytest.mark.asyncio


def adopt(op):
    return {**op, "adopt": True, "original_user_id": op["user_id"]}


def _token(user_id: str, *, age_minutes: float) -> dict:
    now = datetime.now(timezone.utc)
    tok = jwt.encode(
        {"sub": user_id, "type": "access", "iat": now - timedelta(minutes=age_minutes), "exp": now + timedelta(hours=1)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {tok}"}


async def _audit_adopt(db):
    return (await db.execute(select(AuditLog).where(AuditLog.action == "sync_adopt"))).scalars().all()


async def test_adopt_with_fresh_token_ok_and_issue_time_audited(client, ctx, db_session):
    op = adopt(dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"]))
    [res] = await _send(client, _token(ctx["admin_id"], age_minutes=14), op)
    assert res["result"] == "applied"
    [audit] = await _audit_adopt(db_session)
    assert audit.after_data["token_issued_at"] is not None


async def test_adopt_with_stale_token_rejected_nothing_written(client, ctx, db_session):
    op = adopt(dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"]))
    [res] = await _send(client, _token(ctx["admin_id"], age_minutes=16), op)
    assert res["result"] == "rejected" and res["code"] == "ADOPT_REAUTH_REQUIRED"
    for model in (ClientOperation, BorrowTransaction, ExportEvent):
        assert (await db_session.execute(select(func.count()).select_from(model))).scalar_one() == 0
    assert await _audit_adopt(db_session) == []


async def test_non_adopt_ops_unaffected_by_old_token(client, ctx):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    [res] = await _send(client, _token(ctx["staff_id"], age_minutes=300), op)
    assert res["result"] == "applied"


async def test_adopted_op_ending_in_conflict_has_adopter_in_ledger_no_adopt_audit(client, ctx, db_session):
    await _send(client, ctx["staff"], dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1))
    loser = adopt(dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1))  # equipment already out
    [res] = await _send(client, ctx["admin"], loser)
    assert res["result"] == "conflict"
    row = (
        await db_session.execute(select(ClientOperation).where(ClientOperation.op_id == uuid.UUID(loser["op_id"])))
    ).scalar_one()
    assert str(row.user_id) == ctx["staff_id"] and str(row.submitted_by_user_id) == ctx["admin_id"]
    assert row.adopted_at is not None
    assert await _audit_adopt(db_session) == []


async def test_adopting_pending_row_created_by_original_user(client, ctx, db_session):
    d = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    r = receipt_op(ctx["staff_id"], d["op_id"], device_id=d["device_id"], seq=2)
    [pending] = await _send(client, ctx["staff"], r)  # dispatch not known yet
    assert pending["result"] == "retry_later"
    await _send(client, ctx["staff"], d)
    [res] = await _send(client, ctx["admin"], adopt(r))
    assert res["result"] == "applied"
    row = (
        await db_session.execute(select(ClientOperation).where(ClientOperation.op_id == uuid.UUID(r["op_id"])))
    ).scalar_one()
    assert str(row.user_id) == ctx["staff_id"] and str(row.submitted_by_user_id) == ctx["admin_id"]
    assert row.adopted_at is not None
