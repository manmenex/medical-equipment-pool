"""Roadmap PR15A regression coverage: structured logging, request/correlation
ID propagation via ContextVar, the one-per-request access-log event, and the
"never a dependency for request success / never sensitive data" invariants.

Mirrors backend/tests/test_redis_failure_logging.py's established pattern:
assert against captured LogRecord objects (caplog), not formatted handler
output -- pytest's caplog attaches its own handler independent of
app.core.logging.configure_logging()'s JSON formatter/handler, so these
tests exercise the same records that formatter would receive without
depending on stdout capture.
"""

import asyncio
import logging
import uuid

import pytest

from app import main as main_module
from app.core.log_context import correlation_id_var, job_run_id_var, request_id_var
from app.core.logging import JsonFormatter, configure_logging
from app.worker.scheduler import check_pm_cal_due
from tests.conftest import auth_headers

# Route *template* as SQLAlchemy/Starlette records it on request.scope["route"]
# -- relative to the equipment APIRouter's own prefix (/equipment), not
# including the outer /api/v1 mount prefix added when it's included into
# api_router. This is exactly what request.scope.get("route").path reports.
EQUIPMENT_DETAIL_ROUTE = "/equipment/{equipment_id}"


def _access_records(caplog):
    return [r for r in caplog.records if r.name == main_module.access_logger.name]


async def test_exactly_one_access_event_per_request(client, seeded_users, caplog):
    headers = await auth_headers(client)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=main_module.access_logger.name):
        resp = await client.get(f"/api/v1/equipment/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
    records = _access_records(caplog)
    assert len(records) == 1, f"expected exactly one access-log event, got {len(records)}"


async def test_access_log_uses_route_template_not_raw_url(client, seeded_users, caplog):
    headers = await auth_headers(client)
    id1, id2 = uuid.uuid4(), uuid.uuid4()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=main_module.access_logger.name):
        resp1 = await client.get(f"/api/v1/equipment/{id1}", headers=headers)
        resp2 = await client.get(f"/api/v1/equipment/{id2}", headers=headers)
    assert resp1.status_code == 404
    assert resp2.status_code == 404
    records = _access_records(caplog)
    assert len(records) == 2
    routes = {r.http_route for r in records}
    # Two different equipment IDs must collapse to the SAME templated
    # route, not two distinct high-cardinality raw-URL entries.
    assert routes == {EQUIPMENT_DETAIL_ROUTE}, routes
    for r in records:
        assert str(id1) not in r.http_route
        assert str(id2) not in r.http_route


async def test_unmatched_route_falls_back_to_fixed_label(client, seeded_users, caplog):
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=main_module.access_logger.name):
        resp = await client.get("/api/v1/this-path-does-not-exist-anywhere")
    assert resp.status_code == 404
    records = _access_records(caplog)
    assert len(records) == 1
    assert records[0].http_route == "unmatched"


async def test_concurrent_requests_do_not_cross_contaminate_request_id(client, seeded_users, caplog):
    """Direct test of the ContextVar approach's safety under real concurrent
    request handling (Roadmap PR15A design requirement): two requests in
    flight at once must each see their own request_id in captured log
    records, never the other request's."""
    headers = await auth_headers(client)
    req_id_a = "concurrent-request-id-a-" + uuid.uuid4().hex[:8]
    req_id_b = "concurrent-request-id-b-" + uuid.uuid4().hex[:8]

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=main_module.access_logger.name):
        resp_a, resp_b = await asyncio.gather(
            client.get(f"/api/v1/equipment/{uuid.uuid4()}", headers={**headers, "X-Request-ID": req_id_a}),
            client.get(f"/api/v1/equipment/{uuid.uuid4()}", headers={**headers, "X-Request-ID": req_id_b}),
        )

    assert resp_a.status_code == 404
    assert resp_b.status_code == 404
    assert resp_a.headers["x-request-id"] == req_id_a
    assert resp_b.headers["x-request-id"] == req_id_b

    records = _access_records(caplog)
    assert len(records) == 2
    seen_ids = {r.request_id for r in records}
    assert seen_ids == {req_id_a, req_id_b}, (
        f"expected each concurrent request's log record to carry its own request_id, got {seen_ids}"
    )


async def test_context_var_is_reset_after_request_completes(client, seeded_users):
    """ContextVar reset in `finally` (Roadmap PR15A requirement): once a
    request finishes, request_id_var/correlation_id_var must be back to
    their unset default in this task's context -- otherwise a later log
    call issued outside any request (or a reused worker task) would
    incorrectly inherit a stale request_id."""
    assert request_id_var.get() is None
    assert correlation_id_var.get() is None

    resp = await client.get(f"/api/v1/equipment/{uuid.uuid4()}", headers=await auth_headers(client))
    assert resp.status_code == 404

    assert request_id_var.get() is None, "request_id_var leaked past the request's finally block"
    assert correlation_id_var.get() is None, "correlation_id_var leaked past the request's finally block"


async def test_oversized_request_id_is_not_logged_fallback_id_is(client, seeded_users, caplog):
    headers = await auth_headers(client)
    oversized = "x" * 200
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=main_module.access_logger.name):
        resp = await client.get(
            f"/api/v1/equipment/{uuid.uuid4()}",
            headers={**headers, "X-Request-ID": oversized},
        )
    assert resp.status_code == 404
    generated_id = resp.headers["x-request-id"]
    assert generated_id != oversized
    records = _access_records(caplog)
    assert len(records) == 1
    assert records[0].request_id == generated_id
    assert oversized not in records[0].request_id


async def test_unsafe_characters_in_request_id_are_not_logged(client, seeded_users, caplog):
    headers = await auth_headers(client)
    unsafe = "not safe; DROP TABLE users;\n"
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=main_module.access_logger.name):
        resp = await client.get(
            f"/api/v1/equipment/{uuid.uuid4()}",
            headers={**headers, "X-Request-ID": unsafe},
        )
    assert resp.status_code == 404
    generated_id = resp.headers["x-request-id"]
    records = _access_records(caplog)
    assert records[0].request_id == generated_id
    assert "DROP TABLE" not in records[0].request_id
    assert "\n" not in records[0].request_id


async def test_domain_error_exception_path_carries_request_id(client, seeded_users, caplog):
    headers = await auth_headers(client)
    req_id = "domain-error-path-" + uuid.uuid4().hex[:8]
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=main_module.logger.name):
        resp = await client.get(
            f"/api/v1/equipment/{uuid.uuid4()}",
            headers={**headers, "X-Request-ID": req_id},
        )
    assert resp.status_code == 404
    matching = [r for r in caplog.records if getattr(r, "request_id", None) == req_id]
    assert matching, "expected the DomainError handler's log line to carry request_id"


async def test_validation_error_exception_path_carries_request_id(client, seeded_users, caplog):
    headers = await auth_headers(client)
    req_id = "validation-error-path-" + uuid.uuid4().hex[:8]
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=main_module.logger.name):
        resp = await client.get(
            "/api/v1/equipment/not-a-valid-uuid",
            headers={**headers, "X-Request-ID": req_id},
        )
    assert resp.status_code == 422
    matching = [r for r in caplog.records if getattr(r, "request_id", None) == req_id]
    assert matching, "expected the RequestValidationError handler's log line to carry request_id"


async def test_http_exception_path_carries_request_id(client, seeded_users, caplog):
    req_id = "http-exception-path-" + uuid.uuid4().hex[:8]
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=main_module.logger.name):
        resp = await client.get(
            f"/api/v1/equipment/{uuid.uuid4()}",
            headers={"X-Request-ID": req_id},  # no Authorization header -> 401
        )
    assert resp.status_code == 401
    matching = [r for r in caplog.records if getattr(r, "request_id", None) == req_id]
    assert matching, "expected the StarletteHTTPException handler's log line to carry request_id"


async def test_unhandled_exception_path_carries_request_id(client, seeded_users, caplog, monkeypatch):
    # Starlette's ServerErrorMiddleware always re-raises after sending a 500
    # response (so real ASGI servers can log it); httpx's ASGITransport
    # re-raises that into the caller by default. Mirrors
    # tests/test_exception_handling.py's `_raw_client()` pattern.
    from httpx import ASGITransport, AsyncClient

    from app.crud import equipment as equipment_crud
    from app.main import app as fastapi_app

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr(equipment_crud, "get_by_id", _boom)

    headers = await auth_headers(client)
    req_id = "unhandled-exception-path-" + uuid.uuid4().hex[:8]
    caplog.clear()
    transport = ASGITransport(app=fastapi_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as raw_client:
        with caplog.at_level(logging.INFO, logger=main_module.logger.name):
            resp = await raw_client.get(
                f"/api/v1/equipment/{uuid.uuid4()}",
                headers={**headers, "X-Request-ID": req_id},
            )
    assert resp.status_code == 500
    matching = [
        r for r in caplog.records if getattr(r, "request_id", None) == req_id and r.levelno == logging.ERROR
    ]
    assert matching, "expected the unhandled-exception handler's log line to carry request_id"
    assert matching[0].exc_info is not None


async def test_logging_failure_never_affects_request_outcome(client, seeded_users, monkeypatch):
    """Logging must never become a dependency for request success (Roadmap
    PR15A requirement): a broken access-log emission must not turn a
    successful request into a failure, and must not mask a real error
    response either."""

    def _broken_info(*_args, **_kwargs):
        raise RuntimeError("simulated logging subsystem failure")

    monkeypatch.setattr(main_module.access_logger, "info", _broken_info)

    resp = await client.get(f"/api/v1/equipment/{uuid.uuid4()}", headers=await auth_headers(client))
    assert resp.status_code == 404, "a broken access-log call must not change the real response"

    # The ContextVar reset must still happen even when the access-log
    # emission itself raised.
    assert request_id_var.get() is None
    assert correlation_id_var.get() is None


async def test_wrong_password_login_never_logs_the_password(client, seeded_users, caplog):
    secret_password = "TotallyRealSecretPassword!42"
    with caplog.at_level(logging.DEBUG):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "ADMINISTRATOR001", "password": secret_password},
        )
    assert resp.status_code in (401, 422)
    formatter = JsonFormatter()
    for record in caplog.records:
        assert secret_password not in record.getMessage()
        assert secret_password not in formatter.format(record)


async def test_json_formatter_never_includes_unrecognized_extra_fields(caplog):
    """Only the explicit allowlist in app.core.logging._EXTRA_FIELDS may
    appear -- a stray `extra={"bcm_code": ...}` (or similar) at some future
    call site must not silently reach the formatted output."""
    formatter = JsonFormatter()
    logger = logging.getLogger("test.observability.sensitive")
    with caplog.at_level(logging.INFO, logger=logger.name):
        logger.info(
            "test message",
            extra={
                "http_method": "GET",
                "bcm_code": "BCM00001",
                "item_no": "ITEM-SECRET",
                "password": "should-never-appear",
            },
        )
    record = caplog.records[-1]
    payload = formatter.format(record)
    assert "http_method" in payload  # allowlisted field present
    assert "BCM00001" not in payload
    assert "ITEM-SECRET" not in payload
    assert "should-never-appear" not in payload


async def test_import_success_log_contains_only_aggregate_statistics(caplog, monkeypatch):
    """Aggregate import logging (Roadmap PR15A): the success log line must
    carry only row-count statistics, never the filename or row/cell
    content."""
    from app.services import import_service

    class _FakePlanResult:
        def __init__(self, status):
            self.status = status

    class _FakePlan:
        def __init__(self):
            self.result = _FakePlanResult(import_service.ImportRowStatus.SUCCESS)
            self.equipment_id = uuid.uuid4()
            self.import_source_metadata = {"secret_cell_value": "should-never-be-logged"}
            self.update_data = {}

    class _FakeEquipment:
        equipment_metadata = {}
        id = uuid.uuid4()

    class _FakeAuditLog:
        id = uuid.uuid4()

    class _FakeDB:
        async def commit(self):
            return None

        async def rollback(self):
            return None

    async def _fake_get_by_id(_db, _id):
        return _FakeEquipment()

    async def _fake_update(_db, _existing, *, data):
        return None

    async def _fake_record_audit_event(*_args, **_kwargs):
        return _FakeAuditLog()

    monkeypatch.setattr(import_service.equipment_crud, "get_by_id", _fake_get_by_id)
    monkeypatch.setattr(import_service.equipment_crud, "update", _fake_update)
    monkeypatch.setattr(import_service, "record_audit_event", _fake_record_audit_event)

    plans = [_FakePlan()]
    with caplog.at_level(logging.INFO, logger=import_service.logger.name):
        summary = await import_service._commit_rows(
            _FakeDB(),
            filename="super-secret-filename-should-not-be-logged.xlsx",
            plans=plans,
            update_existing=True,
            actor_user_id=None,
            request=None,
        )

    assert summary.succeeded == 1
    success_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert success_records, "expected a success log line on successful commit"
    formatter = JsonFormatter()
    for record in success_records:
        payload = formatter.format(record)
        assert "super-secret-filename-should-not-be-logged.xlsx" not in payload
        assert "should-never-be-logged" not in payload
    assert getattr(success_records[-1], "total_rows", None) == 1
    assert getattr(success_records[-1], "succeeded", None) == 1


async def test_scheduler_job_run_id_is_isolated_and_reset(monkeypatch, db_engine):
    """Background-job run IDs must be independent of the HTTP
    request_id/correlation_id mechanism (Roadmap PR15A requirement)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.worker import scheduler as scheduler_module

    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(scheduler_module, "AsyncSessionLocal", session_maker)

    assert job_run_id_var.get() is None
    await check_pm_cal_due()
    assert job_run_id_var.get() is None, "job_run_id_var leaked past the scheduled run's finally block"


async def test_scheduler_failure_is_logged_with_run_id_and_reraised(monkeypatch, db_engine, caplog):
    from app.worker import scheduler as scheduler_module

    class _BoomSession:
        async def __aenter__(self):
            raise RuntimeError("simulated scheduler failure")

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(scheduler_module, "AsyncSessionLocal", _BoomSession)

    with caplog.at_level(logging.ERROR, logger=scheduler_module.logger.name):
        with pytest.raises(RuntimeError, match="simulated scheduler failure"):
            await check_pm_cal_due()

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "expected the scheduler failure to be logged, not silent"
    assert error_records[0].job_run_id is not None
    assert job_run_id_var.get() is None, "job_run_id_var must still be reset even when the job raised"


def test_configure_logging_is_idempotent_when_handlers_already_exist():
    """PR #50 merge-review fix: logging.basicConfig() is a silent no-op
    once the root logger already has *any* handler (unless force=True) --
    so whichever of Uvicorn, pytest, or app.core.logging happens to run
    first would otherwise decide, by accident of import order, whether
    application logs come out as JSON or as whatever that other caller
    installed. configure_logging() must not depend on basicConfig's
    default idempotency: it must always end up with exactly one JSON
    handler installed, regardless of what was already there, and calling
    it twice must never accumulate a second handler."""
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        # Simulate another caller (e.g. Uvicorn's own logging setup, which
        # -- depending on import order -- can run before this module is
        # ever imported) having already installed a plain-text handler.
        pre_existing = logging.StreamHandler()
        pre_existing.setFormatter(logging.Formatter("%(message)s"))
        root.handlers = [pre_existing]

        configure_logging(debug=False)
        assert len(root.handlers) == 1, "expected exactly one handler after configure_logging()"
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

        # Calling it again (e.g. a second create_app() in the same
        # process) must not leave a duplicate handler installed.
        configure_logging(debug=False)
        assert len(root.handlers) == 1, "configure_logging() must be idempotent, not additive"
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


async def test_post_commit_logging_failure_does_not_convert_success_into_failure(monkeypatch):
    """PR #50 merge-review fix (primary merge blocker): once db.commit()
    has already succeeded, a failure in the subsequent success-log call
    must never propagate back to the caller. That would turn an
    already-committed, successful import batch into an HTTP 500 --
    misrepresenting a real success as a failure and inviting the client to
    unsafely retry work that was, in fact, already applied."""
    from app.services import import_service

    class _FakePlanResult:
        def __init__(self, status):
            self.status = status

    class _FakePlan:
        def __init__(self):
            self.result = _FakePlanResult(import_service.ImportRowStatus.SUCCESS)
            self.equipment_id = uuid.uuid4()
            self.import_source_metadata = {}
            self.update_data = {}

    class _FakeEquipment:
        equipment_metadata = {}
        id = uuid.uuid4()

    class _FakeAuditLog:
        id = uuid.uuid4()

    commit_calls: list[bool] = []

    class _FakeDB:
        async def commit(self):
            commit_calls.append(True)

        async def rollback(self):
            raise AssertionError(
                "rollback must not be triggered by a logging-only failure that happens after commit"
            )

    async def _fake_get_by_id(_db, _id):
        return _FakeEquipment()

    async def _fake_update(_db, _existing, *, data):
        return None

    async def _fake_record_audit_event(*_args, **_kwargs):
        return _FakeAuditLog()

    def _broken_info(*_args, **_kwargs):
        raise RuntimeError("simulated logging subsystem failure")

    monkeypatch.setattr(import_service.equipment_crud, "get_by_id", _fake_get_by_id)
    monkeypatch.setattr(import_service.equipment_crud, "update", _fake_update)
    monkeypatch.setattr(import_service, "record_audit_event", _fake_record_audit_event)
    monkeypatch.setattr(import_service.logger, "info", _broken_info)

    plans = [_FakePlan()]
    summary = await import_service._commit_rows(
        _FakeDB(),
        filename="upload.xlsx",
        plans=plans,
        update_existing=True,
        actor_user_id=None,
        request=None,
    )

    assert commit_calls == [True], "the database commit must have actually gone through"
    assert summary.succeeded == 1
    assert summary.failed == 0
    assert summary.audit_log_id is not None, "the committed batch's audit_log_id must still be reported"
