import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core import export_hn
from app.models.client_operation import (
    OP_STATUS_APPLIED,
    OP_STATUS_CONFLICT,
    OP_STATUS_PENDING,
    OP_STATUS_RESOLVED,
    ClientOperation,
)
from app.models.system_heartbeat import HEARTBEAT_LEGACY_SHEET_SYNC
from app.models.user import ROLE_EQUIPMENT_POOL_STAFF
from app.services import health_alert_service as svc
from tests.conftest import auth_headers

URL = "/api/v1/system/health-alerts"
NOW = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
ON = {"LEGACY_SHEET_SYNC_ENABLED": "true"}


@pytest.fixture(autouse=True)
def _reset_hn(monkeypatch):
    monkeypatch.setattr(export_hn, "_last_startup", None)
    monkeypatch.delenv("LEGACY_SHEET_SYNC_ENABLED", raising=False)
    monkeypatch.delenv("EXPORT_HN_PORT", raising=False)


def _codes(alerts):
    return [a["code"] for a in alerts]


async def _op(db, user, status, first_seen=NOW):
    db.add(ClientOperation(
        op_id=uuid.uuid4(), device_id=uuid.uuid4(), device_seq=1, user_id=user.id, op_type="dispatch",
        payload_hash="0" * 64, status=status, payload={}, first_seen_at=first_seen,
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_sync_stale_only_when_enabled_and_old(db_session):
    await svc.record_heartbeat(db_session, HEARTBEAT_LEGACY_SHEET_SYNC, NOW - timedelta(minutes=20))
    assert _codes(await svc.compute_alerts(db_session, NOW, env={})) == []  # disabled
    alerts = await svc.compute_alerts(db_session, NOW, env=ON)
    assert _codes(alerts) == ["sync_stale"] and "20" in alerts[0]["message_th"]
    await svc.record_heartbeat(db_session, HEARTBEAT_LEGACY_SHEET_SYNC, NOW - timedelta(minutes=5))
    assert _codes(await svc.compute_alerts(db_session, NOW, env=ON)) == []


@pytest.mark.asyncio
async def test_sync_enabled_without_heartbeat_alerts(db_session):
    alerts = await svc.compute_alerts(db_session, NOW, env=ON)
    assert _codes(alerts) == ["sync_stale"] and alerts[0]["since"] is None


@pytest.mark.asyncio
async def test_review_queue_counts_open_items_only(db_session, seeded_users):
    u = seeded_users[ROLE_EQUIPMENT_POOL_STAFF]
    assert _codes(await svc.compute_alerts(db_session, NOW, env={})) == []
    await _op(db_session, u, OP_STATUS_CONFLICT)
    await _op(db_session, u, OP_STATUS_PENDING, first_seen=NOW - timedelta(days=3))  # aged out
    await _op(db_session, u, OP_STATUS_PENDING)  # still inside window
    await _op(db_session, u, OP_STATUS_RESOLVED)  # dismissed
    await _op(db_session, u, OP_STATUS_APPLIED)
    alerts = await svc.compute_alerts(db_session, NOW, env={})
    assert _codes(alerts) == ["sync_review_queue"] and "2 รายการ" in alerts[0]["message_th"]


@pytest.mark.asyncio
async def test_hn_listener_alert_only_when_port_set_and_refused(db_session):
    class Cfg:
        EXPORT_HN_PORT = 8000
        APP_PORT = 8000
        EXPORT_HN_ALLOWED_PEERS = "10.0.0.0/8"

    export_hn.log_startup_check(Cfg)  # port equals app port -> refused
    assert _codes(await svc.compute_alerts(db_session, NOW, env={})) == []  # EXPORT_HN_PORT not set in env
    alerts = await svc.compute_alerts(db_session, NOW, env={"EXPORT_HN_PORT": "8000"})
    assert _codes(alerts) == ["hn_listener_disabled"]
    Cfg.EXPORT_HN_PORT = 9100
    export_hn.log_startup_check(Cfg)  # healthy
    assert _codes(await svc.compute_alerts(db_session, NOW, env={"EXPORT_HN_PORT": "9100"})) == []


@pytest.mark.asyncio
async def test_endpoint_admin_only(client, seeded_users):
    ok = await client.get(URL, headers=await auth_headers(client))
    assert ok.status_code == 200 and ok.json() == []
    staff = await client.get(URL, headers=await auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF))
    assert staff.status_code == 403
    assert (await client.get(URL)).status_code in (401, 403)


@pytest.mark.asyncio
async def test_restore_drill_alert_raise_and_clear(db_session):
    from app.scripts.record_ops_status import record

    assert _codes(await svc.compute_alerts(db_session, NOW, env={})) == []
    await record(db_session, "restore_drill", "fail")
    alerts = await svc.compute_alerts(db_session, NOW, env={})
    assert _codes(alerts) == ["restore_drill_failed"]
    assert alerts[0]["severity"] == "high"
    assert alerts[0]["message_th"] == "ระบบทดสอบกู้คืนรายเดือนมีปัญหา: ไม่ผ่าน 5 ครั้งในเดือนนี้ ตรวจไฟล์ logs\\restore-drill"
    await record(db_session, "restore_drill", "fail")  # idempotent update, still one alert
    assert _codes(await svc.compute_alerts(db_session, NOW, env={})) == ["restore_drill_failed"]
    await record(db_session, "restore_drill", "pass")
    assert _codes(await svc.compute_alerts(db_session, NOW, env={})) == []


@pytest.mark.asyncio
async def test_restore_drill_stale_after_40_days(db_session):
    await svc.record_restore_drill(db_session, "pass", NOW - timedelta(days=39))
    assert _codes(await svc.compute_alerts(db_session, NOW, env={})) == []
    await svc.record_restore_drill(db_session, "pass", NOW - timedelta(days=41))
    assert _codes(await svc.compute_alerts(db_session, NOW, env={})) == ["restore_drill_stale"]


def test_record_ops_status_cli_args():
    from app.scripts.record_ops_status import parse_args

    a = parse_args(["--code", "restore_drill", "--status", "fail", "--detail", "5 failures"])
    assert (a.code, a.status) == ("restore_drill", "fail")
    for bad in (["--code", "other", "--status", "pass"], ["--code", "restore_drill", "--status", "maybe"],
                ["--code", "restore_drill", "--status", "pass", "--detail", "a\nb"],
                ["--code", "restore_drill", "--status", "pass", "--detail", "x" * 201]):
        with pytest.raises(SystemExit):
            parse_args(bad)
