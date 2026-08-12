"""Roadmap PR20A (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §6.2,
§6.4, §6.5, §18, §21, architecture-approved via the merged Design PR #89).

Covers the source artifact infrastructure slice only -- upload/
registration (server-authoritative checksum/length, the metadata-only
guard for `dataset_type="equipment_master"`), the DB+blob transaction
contract, `ImportSourceReader`/`VerifiedSourceContent`, `AdapterInvocation
Context`, retention integration, security/resource bounds, and RBAC. No
Equipment Master parser, field mapping, or Equipment mutation exists yet
(§24 PR20A scope) -- this module registers only a fake/capturing test
adapter, exactly like `test_import_validation.py`/`test_import_execution.py`
do for PR19A2/PR19A3."""

import hashlib
import io
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.crud import import_retention as import_retention_crud
from app.crud import import_session as import_crud
from app.crud import import_source_blob as import_source_blob_crud
from app.models.import_session import ImportJob, ImportSession, ImportSource, ImportSourceBlob
from app.models.user import User
from app.services import import_execution_service, import_lease, import_service
from app.services.import_adapter import DryRunPlan, ImportAdapter, RawImportRecord, register_adapter, unregister_adapter
from app.services.import_adapter_context import get_adapter_invocation_context
from app.services.import_source_reader import (
    ImportSourceReader,
    SourceBlobMissingError,
    SourceChecksumMismatchError,
    SourceDescriptor,
    SourceLengthMismatchError,
    VerifiedSourceContent,
)
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

DATASET_TYPE = "pr20a_test_dataset"
EQUIPMENT_MASTER_DATASET_TYPE = "equipment_master"
UPLOAD_URL_SUFFIX = "/source/upload"


def _build_xlsx_bytes(payload: bytes = b"stub-workbook-content", *, entry_name: str = "[Content_Types].xml") -> bytes:
    """A minimal, validly-structured ZIP archive satisfying
    `import_service._validate_zip_archive_bounds`'s allowed-entry-path
    check -- not a genuine OOXML workbook (this slice ships no XLSX
    parser, §24), just bytes shaped enough to pass the upload endpoint's
    reused PR12 bounds/structure checks."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(entry_name, payload)
    return buf.getvalue()


def _build_raw_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buf.getvalue()


class CapturingAdapter(ImportAdapter):
    """Test/fake adapter (mirrors `test_import_validation.py`'s
    `FakeAdapter` convention). Records exactly what the framework hands it
    at each call site, so tests can assert PR20A's wiring structurally --
    what `parse()` receives, what `AdapterInvocationContext` is visible
    during `plan_dry_run`/`execute` -- rather than by inference."""

    dataset_type = DATASET_TYPE
    ruleset_version = "pr20a-test-ruleset"

    def __init__(self):
        self.parse_calls = 0
        self.last_raw_input: object = "UNSET"
        self.dry_run_calls = 0
        self.dry_run_context = None
        self.execute_calls = 0
        self.execute_context = None

    def parse(self, raw_input):
        self.parse_calls += 1
        self.last_raw_input = raw_input
        return [RawImportRecord(row_number=1, fields={})]

    def validate_business_rules(self, record, context):
        return []

    async def plan_dry_run(self, db):
        self.dry_run_calls += 1
        self.dry_run_context = get_adapter_invocation_context()
        return DryRunPlan()

    async def execute(self, db):
        self.execute_calls += 1
        self.execute_context = get_adapter_invocation_context()
        return 1


@pytest_asyncio.fixture(autouse=True)
async def _patch_session_factories(db_engine, monkeypatch):
    """Mirrors `test_import_validation.py`/`test_import_execution.py`'s
    identical fixture: every module that opens its own `AsyncSessionLocal()`
    (the lease renewal loop, TX2/TX3) must be repointed at this test
    module's own `db_engine`, since this suite exercises validate,
    dry-run, *and* execute."""
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(import_lease, "AsyncSessionLocal", session_maker)
    monkeypatch.setattr(import_execution_service, "AsyncSessionLocal", session_maker)


@pytest_asyncio.fixture
async def capturing_adapter():
    adapter = CapturingAdapter()
    register_adapter(adapter)
    yield adapter
    unregister_adapter(DATASET_TYPE)


async def _create_session(client: AsyncClient, headers: dict, *, dataset_type: str = DATASET_TYPE) -> dict:
    r = await client.post("/api/v1/import-sessions", headers=headers, json={"dataset_type": dataset_type})
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _upload_source(
    client: AsyncClient,
    headers: dict,
    session_id: str,
    *,
    content: bytes | None = None,
    filename: str = "source.xlsx",
    content_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    checksum: str | None = None,
    source_version: str | None = None,
):
    content = content if content is not None else _build_xlsx_bytes()
    files = {"file": (filename, content, content_type)}
    data = {}
    if checksum is not None:
        data["checksum"] = checksum
    if source_version is not None:
        data["source_version"] = source_version
    return await client.post(f"/api/v1/import-sessions/{session_id}{UPLOAD_URL_SUFFIX}", headers=headers, files=files, data=data)


async def _create_uploaded_session(client: AsyncClient, headers: dict, *, content: bytes | None = None) -> tuple[dict, bytes]:
    session = await _create_session(client, headers)
    content = content if content is not None else _build_xlsx_bytes()
    resp = await _upload_source(client, headers, session["id"], content=content)
    assert resp.status_code == 201, resp.text
    return session, content


async def _create_validated_uploaded_session(client: AsyncClient, headers: dict) -> tuple[dict, bytes]:
    session, content = await _create_uploaded_session(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "validated", r.text
    return body, content


async def _create_dry_run_completed_uploaded_session(client: AsyncClient, headers: dict) -> tuple[dict, bytes]:
    session, content = await _create_validated_uploaded_session(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "dry_run_completed", r.text
    return body, content


async def _raw_client():
    """A test client that lets an unhandled exception's 500 response reach
    the caller instead of re-raising it (mirrors
    `test_exception_handling.py`'s identical helper): Starlette's
    `ServerErrorMiddleware` always re-raises after sending its 500
    response so a real ASGI server can log it; httpx's `ASGITransport`
    re-raises that into the caller by default. `client` (this module's
    normal fixture) must still be depended on by the calling test so its
    `app.dependency_overrides` are in effect for this raw client too --
    both share the same `app` instance."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def _get_user_id(db_session, role: str = "administrator") -> uuid.UUID:
    result = await db_session.execute(select(User).where(User.employee_code == f"{role.upper()}001"))
    return result.scalar_one().id


async def _make_registered_source(db_session, *, session_id: uuid.UUID, content: bytes) -> ImportSource:
    """Direct-DB helper for `ImportSourceReader` unit tests -- builds a
    correctly-registered `ImportSource` + matching `ImportSourceBlob` row
    without going through the HTTP upload endpoint, so a test can then
    deliberately corrupt one field to prove `open_verified`'s independent
    read-time checks (§6.5)."""
    source = ImportSource(
        import_session_id=session_id,
        status="registered",
        checksum=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        options_fingerprint="x",
        source_fingerprint="y",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.flush()
    db_session.add(ImportSourceBlob(import_source_id=source.id, content=content))
    await db_session.commit()
    return source


def _descriptor_for(source: ImportSource, *, session_id: uuid.UUID) -> SourceDescriptor:
    return SourceDescriptor(
        import_source_id=source.id,
        import_session_id=session_id,
        dataset_type=DATASET_TYPE,
        expected_checksum=source.checksum,
        expected_byte_size=source.byte_size,
        content_type=source.content_type,
        original_filename=source.filename,
        registration_status=source.status,
    )


# ---------------------------------------------------------------------------
# Registration / upload endpoint (§6.2)
# ---------------------------------------------------------------------------


async def test_upload_source_success_server_derives_checksum_and_byte_size(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    content = _build_xlsx_bytes()

    resp = await _upload_source(client, headers, session["id"], content=content)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["checksum"] == hashlib.sha256(content).hexdigest(), "checksum must be server-derived, never trusted from the client"
    assert body["byte_size"] == len(content)
    assert body["status"] == "registered"


async def test_upload_source_client_checksum_matching_server_is_accepted(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    content = _build_xlsx_bytes()
    correct_checksum = hashlib.sha256(content).hexdigest()

    resp = await _upload_source(client, headers, session["id"], content=content, checksum=correct_checksum)
    assert resp.status_code == 201, resp.text
    assert resp.json()["checksum"] == correct_checksum


async def test_upload_source_client_checksum_mismatch_rejected_before_any_write(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    content = _build_xlsx_bytes()

    resp = await _upload_source(client, headers, session["id"], content=content, checksum="f" * 64)
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"

    sources = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == uuid.UUID(session["id"])))
    ).scalars().all()
    assert sources == [], "an advisory client checksum mismatch must be rejected before any registration write"


async def test_metadata_only_registration_rejected_for_equipment_master(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = await _create_session(client, headers, dataset_type=EQUIPMENT_MASTER_DATASET_TYPE)

    resp = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": "a" * 64, "byte_size": 100},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "IMPORT_SOURCE_REGISTRATION_METHOD_NOT_ALLOWED"

    sources = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == uuid.UUID(session["id"])))
    ).scalars().all()
    assert sources == [], "a rejected metadata-only registration must never leave equipment_master in a registered state with no blob"


async def test_metadata_only_registration_unaffected_for_other_dataset_types(client: AsyncClient, seeded_users):
    """Regression proof: the guard is scoped to exactly `equipment_master`
    -- every other dataset_type keeps PR19A's existing metadata-only
    contract exactly as it shipped."""
    headers = await auth_headers(client)
    session = await _create_session(client, headers, dataset_type=DATASET_TYPE)

    resp = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": "a" * 64, "byte_size": 100},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "registered"


async def test_upload_source_available_for_a_non_equipment_master_dataset_type(client: AsyncClient, seeded_users):
    """The upload endpoint itself is gated on blob-existence at read time,
    not on dataset_type -- any dataset_type may use it."""
    headers = await auth_headers(client)
    session = await _create_session(client, headers, dataset_type=DATASET_TYPE)
    resp = await _upload_source(client, headers, session["id"])
    assert resp.status_code == 201, resp.text


async def test_upload_source_retry_same_bytes_before_freeze_is_idempotent(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    content = _build_xlsx_bytes()

    first = await _upload_source(client, headers, session["id"], content=content)
    assert first.status_code == 201, first.text
    second = await _upload_source(client, headers, session["id"], content=content)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]

    sources = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == uuid.UUID(session["id"])))
    ).scalars().all()
    assert len(sources) == 1, "a retry with identical bytes must never create a second source row"
    blobs = (await db_session.execute(select(ImportSourceBlob))).scalars().all()
    assert len(blobs) == 1


async def test_upload_source_conflicting_bytes_before_freeze_corrects(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    first_content = _build_xlsx_bytes(b"first-version")
    second_content = _build_xlsx_bytes(b"second-version")

    first = await _upload_source(client, headers, session["id"], content=first_content)
    assert first.status_code == 201, first.text
    second = await _upload_source(client, headers, session["id"], content=second_content)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["checksum"] == hashlib.sha256(second_content).hexdigest()

    stored = await import_source_blob_crud.get_content(db_session, import_source_id=uuid.UUID(first.json()["id"]))
    assert stored == second_content, "the correction must overwrite the stored blob, not merely the metadata row"


async def test_upload_source_after_freeze_same_bytes_is_idempotent(client: AsyncClient, seeded_users, capturing_adapter):
    headers = await auth_headers(client)
    session, content = await _create_validated_uploaded_session(client, headers)

    resp = await _upload_source(client, headers, session["id"], content=content)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "frozen"


async def test_upload_source_after_freeze_conflicting_bytes_rejected(client: AsyncClient, seeded_users, capturing_adapter, db_session):
    headers = await auth_headers(client)
    session, original_content = await _create_validated_uploaded_session(client, headers)

    resp = await _upload_source(client, headers, session["id"], content=_build_xlsx_bytes(b"different-bytes"))
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "IMPORT_SOURCE_MISMATCH"

    source = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == uuid.UUID(session["id"])))
    ).scalar_one()
    stored = await import_source_blob_crud.get_content(db_session, import_source_id=source.id)
    assert stored == original_content, "a rejected correction attempt must never mutate the frozen blob"


async def test_upload_source_404_for_unknown_session(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    resp = await _upload_source(client, headers, str(uuid.uuid4()))
    assert resp.status_code == 404
    assert resp.json()["code"] == "IMPORT_SESSION_NOT_FOUND"


async def test_upload_source_requires_administrator(client: AsyncClient, seeded_users):
    staff_headers = await auth_headers(client, role="equipment_pool_staff")
    admin_headers = await auth_headers(client)
    session = await _create_session(client, admin_headers)
    resp = await _upload_source(client, staff_headers, session["id"])
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Blob/DB failure boundary (§6.2's single-transaction atomicity contract)
#
# PR90-H1 fix note: `register_or_correct_source_pending`'s conflict-prone
# INSERT is now isolated in its own SAVEPOINT (`db.begin_nested()`), which
# for the *non-conflicting* case (the scenarios below -- a first-time
# registration, no prior source row) still means a SAVEPOINT is opened and
# released before the later blob-write/finalize failure. pysqlite's default
# legacy transaction handling does not correctly support a released
# SAVEPOINT combined with a later session close-without-commit (the exact,
# separately documented caveat `test_audit.py`'s own `sp_engine` fixture
# works around -- see its docstring for the full rationale and the
# SQLAlchemy recipe reference) -- without that recipe, a released
# SAVEPOINT's row can survive even though the outer session is only ever
# closed, never committed. The three tests below therefore use the same
# dedicated, event-listener-patched SQLite engine/client `test_audit.py`
# already established for this identical class of problem, rather than the
# shared `db_engine`/`client` fixtures used everywhere else in this module
# (which ~50 other tests in this file depend on and must not be changed).
# Real PostgreSQL has no such caveat -- see
# `test_upload_source_finalize_failure_leaves_no_partial_state_on_real_postgres`
# in test_postgres_integration.py for the authoritative, non-quirky proof
# of this exact invariant.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sp_engine():
    from sqlalchemy import event
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    # See https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
    @event.listens_for(engine.sync_engine, "connect")
    def _do_connect(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def _do_begin(conn):
        conn.exec_driver_sql("BEGIN")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def sp_seeded_users(sp_engine):
    from app.core.security import hash_password
    from app.models.user import ALL_ROLES, Role

    session_maker = async_sessionmaker(sp_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        roles = {}
        for name in ALL_ROLES:
            role = Role(name=name, permissions={})
            session.add(role)
            roles[name] = role
        await session.flush()

        users = {}
        for role_name in ALL_ROLES:
            user = User(
                employee_code=f"{role_name.upper()}001",
                full_name=f"Test {role_name}",
                email=f"{role_name}@mep-hospital-test.dev",
                password_hash=hash_password("Password@123"),
                role_id=roles[role_name].id,
            )
            session.add(user)
            users[role_name] = user
        await session.commit()
        return users


@pytest_asyncio.fixture
async def sp_client(sp_engine):
    from app.db.session import get_db
    from app.main import app as sp_app

    session_maker = async_sessionmaker(sp_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with session_maker() as session:
            yield session

    sp_app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=sp_app), base_url="http://test") as ac:
        yield ac
    sp_app.dependency_overrides.clear()


async def _sp_verify_no_source_or_blob(sp_engine, *, session_id: str) -> None:
    """Verifies through a brand-new session/connection -- the same pattern
    `test_audit.py`'s own `_rows_fresh` uses for identical reasons."""
    session_maker = async_sessionmaker(sp_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as verify:
        sources = (
            await verify.execute(select(ImportSource).where(ImportSource.import_session_id == uuid.UUID(session_id)))
        ).scalars().all()
        assert sources == [], "a storage/finalize failure must leave no partial ImportSource row"
        assert (await verify.execute(select(ImportSourceBlob))).scalars().all() == []


async def test_upload_storage_failure_before_finalize_leaves_no_partial_state(
    sp_client: AsyncClient, sp_seeded_users, sp_engine, monkeypatch
):
    import app.api.v1.import_sessions as import_sessions_module

    async def _raise(*_args, **_kwargs):
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(import_sessions_module.import_source_blob_crud, "upsert_pending", _raise)

    headers = await auth_headers(sp_client)
    session = await _create_session(sp_client, headers)
    async with await _raw_client() as raw_client:
        resp = await _upload_source(raw_client, headers, session["id"])
    assert resp.status_code == 500

    await _sp_verify_no_source_or_blob(sp_engine, session_id=session["id"])


async def test_upload_finalize_failure_after_blob_write_rolls_back_both_writes(
    sp_client: AsyncClient, sp_seeded_users, sp_engine, monkeypatch
):
    """The blob INSERT is executed (flushed to the transaction) before the
    simulated failure -- proving rollback discards an already-executed
    statement, not merely an unattempted one."""
    import app.api.v1.import_sessions as import_sessions_module

    original_upsert = import_source_blob_crud.upsert_pending

    async def _upsert_then_raise(db, *, import_source_id, content):
        await original_upsert(db, import_source_id=import_source_id, content=content)
        raise RuntimeError("simulated finalize failure after blob write")

    monkeypatch.setattr(import_sessions_module.import_source_blob_crud, "upsert_pending", _upsert_then_raise)

    headers = await auth_headers(sp_client)
    session = await _create_session(sp_client, headers)
    async with await _raw_client() as raw_client:
        resp = await _upload_source(raw_client, headers, session["id"])
    assert resp.status_code == 500

    await _sp_verify_no_source_or_blob(sp_engine, session_id=session["id"])


async def test_upload_retry_after_failure_succeeds(sp_client: AsyncClient, sp_seeded_users, monkeypatch):
    import app.api.v1.import_sessions as import_sessions_module

    async def _raise(*_args, **_kwargs):
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(import_sessions_module.import_source_blob_crud, "upsert_pending", _raise)
    headers = await auth_headers(sp_client)
    session = await _create_session(sp_client, headers)
    content = _build_xlsx_bytes()

    async with await _raw_client() as raw_client:
        failed = await _upload_source(raw_client, headers, session["id"], content=content)
    assert failed.status_code == 500

    monkeypatch.undo()
    retried = await _upload_source(sp_client, headers, session["id"], content=content)
    assert retried.status_code == 201, retried.text
    assert retried.json()["checksum"] == hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# ImportSourceReader / VerifiedSourceContent (§6.5)
# ---------------------------------------------------------------------------


async def test_open_verified_returns_correct_content(db_session, seeded_users):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    session_id = session.id
    content = b"verified-source-bytes"
    source = await _make_registered_source(db_session, session_id=session_id, content=content)

    result = await ImportSourceReader().open_verified(db_session, _descriptor_for(source, session_id=session_id))
    assert isinstance(result, VerifiedSourceContent)
    assert result.content == content
    assert result.source_descriptor.import_source_id == source.id


async def test_open_verified_missing_blob_raises(db_session, seeded_users):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    session_id = session.id
    source = ImportSource(
        import_session_id=session_id,
        status="registered",
        checksum="a" * 64,
        byte_size=10,
        options_fingerprint="x",
        source_fingerprint="y",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.commit()

    with pytest.raises(SourceBlobMissingError):
        await ImportSourceReader().open_verified(db_session, _descriptor_for(source, session_id=session_id))


async def test_open_verified_checksum_mismatch_raises(db_session, seeded_users):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    session_id = session.id
    content = b"tamper-target-bytes"
    source = await _make_registered_source(db_session, session_id=session_id, content=content)
    # Simulate corruption/tampering strictly between write-time
    # verification and this read: the stored blob no longer matches
    # import_sources.checksum.
    await db_session.execute(
        update(ImportSourceBlob).where(ImportSourceBlob.import_source_id == source.id).values(content=b"corrupted-bytes!!!!")
    )
    await db_session.commit()

    with pytest.raises(SourceChecksumMismatchError):
        await ImportSourceReader().open_verified(db_session, _descriptor_for(source, session_id=session_id))


async def test_open_verified_length_mismatch_raises(db_session, seeded_users):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    session_id = session.id
    content = b"length-tamper-bytes"
    source = await _make_registered_source(db_session, session_id=session_id, content=content)
    await db_session.execute(update(ImportSource).where(ImportSource.id == source.id).values(byte_size=len(content) + 5))
    await db_session.commit()
    await db_session.refresh(source)

    with pytest.raises(SourceLengthMismatchError):
        await ImportSourceReader().open_verified(db_session, _descriptor_for(source, session_id=session_id))


async def test_open_verified_enforces_read_time_bound(db_session, seeded_users, monkeypatch):
    from app.services import import_source_reader as import_source_reader_module

    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    session_id = session.id
    content = b"x" * 64
    source = await _make_registered_source(db_session, session_id=session_id, content=content)
    monkeypatch.setattr(import_source_reader_module, "MAX_UPLOAD_BYTES", 8)

    with pytest.raises(SourceLengthMismatchError):
        await ImportSourceReader().open_verified(db_session, _descriptor_for(source, session_id=session_id))


async def test_open_verified_storage_unavailable_propagates(db_session, seeded_users, monkeypatch):
    from app.services import import_source_reader as import_source_reader_module

    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    session_id = session.id
    source = await _make_registered_source(db_session, session_id=session_id, content=b"anything")

    async def _raise(*_args, **_kwargs):
        raise RuntimeError("simulated storage backend unavailable")

    monkeypatch.setattr(import_source_reader_module.import_source_blob_crud, "get_content", _raise)

    with pytest.raises(RuntimeError, match="simulated storage backend unavailable"):
        await ImportSourceReader().open_verified(db_session, _descriptor_for(source, session_id=session_id))


def test_reader_reuses_pr12_max_upload_bytes_constant_not_a_redefinition():
    from app.services import import_source_reader as import_source_reader_module

    assert import_source_reader_module.MAX_UPLOAD_BYTES is import_service.MAX_UPLOAD_BYTES


# ---------------------------------------------------------------------------
# Framework wiring: validate/dry-run/execute integration (§6.4, §6.5)
# ---------------------------------------------------------------------------


async def test_validate_receives_verified_source_content_for_blob_backed_source(
    client: AsyncClient, seeded_users, capturing_adapter
):
    headers = await auth_headers(client)
    session, content = await _create_uploaded_session(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert r.status_code == 200, r.text

    assert capturing_adapter.parse_calls == 1
    raw_input = capturing_adapter.last_raw_input
    assert isinstance(raw_input, VerifiedSourceContent)
    assert raw_input.content == content
    assert raw_input.source_descriptor.dataset_type == DATASET_TYPE


async def test_validate_receives_none_for_metadata_only_registered_source(client: AsyncClient, seeded_users, capturing_adapter):
    """Regression proof: a source registered via the pre-existing
    metadata-only path has no `import_source_blobs` row, so `parse()`
    still receives `None` exactly as PR19A shipped it."""
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    reg = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": "b" * 64, "byte_size": 42},
    )
    assert reg.status_code == 201, reg.text

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert r.status_code == 200, r.text
    assert capturing_adapter.last_raw_input is None


async def test_dry_run_context_carries_verified_source_content_and_job_ids(client: AsyncClient, seeded_users, capturing_adapter):
    headers = await auth_headers(client)
    validated_session, content = await _create_validated_uploaded_session(client, headers)
    summary = (await client.get(f"/api/v1/import-sessions/{validated_session['id']}", headers=headers)).json()
    validation_job_id = summary["validation_attempt_id"]
    assert validation_job_id is not None

    r = await client.post(f"/api/v1/import-sessions/{validated_session['id']}/dry-run", headers=headers)
    assert r.status_code == 200, r.text

    ctx = capturing_adapter.dry_run_context
    assert ctx is not None
    assert ctx.import_session_id == uuid.UUID(validated_session["id"])
    assert ctx.dataset_type == DATASET_TYPE
    assert ctx.ruleset_version == capturing_adapter.ruleset_version
    assert ctx.verified_source_content is not None
    assert ctx.verified_source_content.content == content
    assert ctx.dry_run_job_id is not None
    assert ctx.accepted_validation_job_id == uuid.UUID(validation_job_id)


async def test_dry_run_context_has_no_verified_source_content_for_metadata_only_source(
    client: AsyncClient, seeded_users, capturing_adapter
):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    reg = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": "c" * 64, "byte_size": 5},
    )
    assert reg.status_code == 201, reg.text
    await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert r.status_code == 200, r.text
    assert capturing_adapter.dry_run_context.verified_source_content is None


async def test_execute_context_never_carries_verified_source_content_or_job_ids(
    client: AsyncClient, seeded_users, capturing_adapter
):
    headers = await auth_headers(client)
    session, _content = await _create_dry_run_completed_uploaded_session(client, headers)

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r.status_code == 200, r.text

    ctx = capturing_adapter.execute_context
    assert ctx is not None
    assert ctx.verified_source_content is None
    assert ctx.dry_run_job_id is None
    assert ctx.accepted_validation_job_id is None
    assert ctx.import_session_id == uuid.UUID(session["id"])


def test_get_adapter_invocation_context_raises_outside_the_frameworks_own_wrapper():
    with pytest.raises(RuntimeError):
        get_adapter_invocation_context()


# ---------------------------------------------------------------------------
# Security / resource bounds (§21)
# ---------------------------------------------------------------------------


async def test_upload_untrusted_filename_stored_verbatim_never_interpreted_as_a_path(client: AsyncClient, seeded_users):
    """`_validate_filename` only checks length/extension -- a path-
    traversal-shaped filename is accepted as opaque metadata text, because
    storage is keyed exclusively by `import_source_id` (a server-generated
    UUID); the filename is never used to construct a storage location."""
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], filename="../../../etc/passwd.xlsx")
    assert resp.status_code == 201, resp.text
    assert resp.json()["filename"] == "../../../etc/passwd.xlsx"


async def test_upload_rejects_disallowed_file_extension(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], filename="notes.txt", content_type="text/plain")
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_upload_rejects_oversized_content(client: AsyncClient, seeded_users, monkeypatch):
    import app.api.v1.import_sessions as import_sessions_module

    monkeypatch.setattr(import_sessions_module, "MAX_UPLOAD_BYTES", 8)
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], content=_build_xlsx_bytes())
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_upload_rejects_content_that_is_not_a_valid_zip_archive(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], content=b"not a zip file at all")
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_upload_rejects_disallowed_zip_entry_path(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], content=_build_raw_zip({"unexpected/payload.bin": b"hi"}))
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_upload_rejects_zip_path_traversal_entry(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], content=_build_raw_zip({"../../etc/passwd": b"hi"}))
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_upload_rejects_all_content_under_a_misconfigured_zero_byte_bound(client: AsyncClient, seeded_users, monkeypatch):
    """Invalid configuration (a bound accidentally set to 0) must fail
    closed -- reject every upload -- rather than silently accepting
    unbounded content."""
    import app.api.v1.import_sessions as import_sessions_module

    monkeypatch.setattr(import_sessions_module, "MAX_UPLOAD_BYTES", 0)
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], content=_build_xlsx_bytes())
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Retention integration (§6.6/§18) -- reuses PR19A's retention system, never
# a second one.
# ---------------------------------------------------------------------------


async def _make_terminal_session_with_blob(
    db_session, *, actor_id: uuid.UUID, status: str, terminal_at, content: bytes = b"legacy-equipment-master-bytes"
) -> tuple[ImportSession, ImportSource]:
    session = ImportSession(dataset_type=DATASET_TYPE, status=status, version=0, created_by_user_id=actor_id, terminal_at=terminal_at)
    db_session.add(session)
    await db_session.flush()
    source = ImportSource(
        import_session_id=session.id,
        status="frozen",
        checksum=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="legacy.xlsx",
        options_fingerprint="x",
        source_fingerprint="y",
        frozen_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.flush()
    db_session.add(ImportSourceBlob(import_source_id=source.id, content=content))
    await db_session.commit()
    return session, source


async def test_retention_purge_deletes_blob_for_eligible_session(client: AsyncClient, seeded_users, db_session):
    actor_id = await _get_user_id(db_session)
    session, source = await _make_terminal_session_with_blob(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200)
    )

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 1

    await db_session.refresh(session)
    assert session.retention_purged_at is not None
    blob = (
        await db_session.execute(select(ImportSourceBlob).where(ImportSourceBlob.import_source_id == source.id))
    ).scalar_one_or_none()
    assert blob is None, "an eligible session's purge must delete its blob together with the metadata redaction"


async def test_retention_does_not_delete_blob_for_non_terminal_session(client: AsyncClient, seeded_users, db_session):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    content = b"active-session-bytes"
    source = ImportSource(
        import_session_id=session.id,
        status="registered",
        checksum=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        options_fingerprint="x",
        source_fingerprint="y",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.flush()
    db_session.add(ImportSourceBlob(import_source_id=source.id, content=content))
    await db_session.commit()

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 0

    blob = (
        await db_session.execute(select(ImportSourceBlob).where(ImportSourceBlob.import_source_id == source.id))
    ).scalar_one_or_none()
    assert blob is not None, "a non-terminal (still in-progress) session's blob must never be purged"


async def test_retention_does_not_delete_blob_for_terminal_session_inside_the_retention_window(
    client: AsyncClient, seeded_users, db_session
):
    actor_id = await _get_user_id(db_session)
    session, source = await _make_terminal_session_with_blob(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=10)
    )

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 0

    blob = (
        await db_session.execute(select(ImportSourceBlob).where(ImportSourceBlob.import_source_id == source.id))
    ).scalar_one_or_none()
    assert blob is not None, "the 180-day retention window must not be weakened for blob-backed sources"


async def test_retention_deletion_failure_leaves_blob_intact_and_session_eligible(
    client: AsyncClient, seeded_users, db_session, monkeypatch
):
    from app.crud import import_retention as retention_crud_module

    actor_id = await _get_user_id(db_session)
    session, source = await _make_terminal_session_with_blob(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200)
    )

    original_redact = retention_crud_module.redact_session

    async def _failing_redact(db, *, session_id, worker_id):
        if session_id == session.id:
            raise RuntimeError("simulated redaction infrastructure failure")
        return await original_redact(db, session_id=session_id, worker_id=worker_id)

    monkeypatch.setattr("app.services.import_retention_service.import_retention_crud.redact_session", _failing_redact)

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["skipped_count"] == 1

    await db_session.refresh(session)
    assert session.retention_purged_at is None, "a failed redaction must remain eligible for a later invocation"
    blob = (
        await db_session.execute(select(ImportSourceBlob).where(ImportSourceBlob.import_source_id == source.id))
    ).scalar_one_or_none()
    assert blob is not None, "a failed redaction attempt must never have deleted the blob"


async def test_retention_cleanup_is_idempotent_after_blob_already_purged(client: AsyncClient, seeded_users, db_session):
    actor_id = await _get_user_id(db_session)
    await _make_terminal_session_with_blob(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200)
    )

    headers = await auth_headers(client)
    first = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert first.json()["purged_count"] == 1
    second = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert second.status_code == 200
    assert second.json()["purged_count"] == 0, "a second retry once the blob is already gone must be a clean no-op, not an error"


async def test_retention_fence_lost_leaves_blob_intact(db_session, seeded_users):
    """§18's fence-loss path, extended: a redaction attempt fenced out by
    a concurrent reclaim must not have deleted the blob either."""
    actor_id = await _get_user_id(db_session)
    session, source = await _make_terminal_session_with_blob(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200)
    )
    session_id = session.id
    source_id = source.id
    worker_a = uuid.uuid4()
    worker_b = uuid.uuid4()
    await import_retention_crud.claim_sessions_for_cleanup(
        db_session, worker_id=worker_a, retention_days=180, claim_timeout_seconds=300, limit=10
    )
    await db_session.execute(
        update(ImportSession)
        .where(ImportSession.id == session_id)
        .values(retention_cleanup_claimed_by=worker_b, retention_cleanup_claim_expires_at=datetime.now(timezone.utc) + timedelta(seconds=300))
    )
    await db_session.commit()

    result = await import_retention_crud.redact_session(db_session, session_id=session_id, worker_id=worker_a)
    assert result is None
    await db_session.rollback()

    blob = (
        await db_session.execute(select(ImportSourceBlob).where(ImportSourceBlob.import_source_id == source_id))
    ).scalar_one_or_none()
    assert blob is not None, "a fenced-out redaction attempt must not have deleted the blob"


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


async def test_upload_source_administrator_succeeds(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"])
    assert resp.status_code == 201, resp.text


async def test_upload_source_read_only_role_rejected(client: AsyncClient, seeded_users):
    read_only_headers = await auth_headers(client, role="read_only")
    admin_headers = await auth_headers(client)
    session = await _create_session(client, admin_headers)
    resp = await _upload_source(client, read_only_headers, session["id"])
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Regression: PR19A validate/dry-run/execute keep working unchanged for a
# metadata-only-registered, non-equipment_master session, end to end.
# ---------------------------------------------------------------------------


async def test_full_metadata_only_pipeline_unaffected_by_pr20a(client: AsyncClient, seeded_users, capturing_adapter, db_session):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    reg = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": "d" * 64, "byte_size": 7},
    )
    assert reg.status_code == 201, reg.text

    v = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert v.status_code == 200 and v.json()["status"] == "validated", v.text
    dr = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert dr.status_code == 200 and dr.json()["status"] == "dry_run_completed", dr.text
    ex = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert ex.status_code == 200 and ex.json()["status"] == "completed", ex.text

    assert capturing_adapter.last_raw_input is None
    assert capturing_adapter.dry_run_context.verified_source_content is None
    assert capturing_adapter.execute_context.verified_source_content is None
    blobs = (await db_session.execute(select(ImportSourceBlob))).scalars().all()
    assert blobs == [], "a metadata-only pipeline must never create an import_source_blobs row"


# ---------------------------------------------------------------------------
# PR90-H1: register_or_correct_source_pending must never decide the fate of
# the caller's outer transaction. Its duplicate/conflict INSERT is isolated
# in its own SAVEPOINT (`db.begin_nested()`) -- resolving that conflict must
# never discard whatever else the caller already wrote in the same,
# still-open transaction. Exercised directly at the CRUD layer with a real
# database session (not a fake/mocked one), proving the externally
# observable invariant, not merely that a function was called.
# ---------------------------------------------------------------------------


async def test_register_or_correct_source_pending_preserves_caller_transaction_on_conflict(db_session, seeded_users):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    session_id = session.id

    existing_content = b"already-registered-bytes"
    db_session.add(
        ImportSource(
            import_session_id=session_id,
            status="registered",
            checksum=hashlib.sha256(existing_content).hexdigest(),
            byte_size=len(existing_content),
            options_fingerprint="x",
            source_fingerprint="pre-existing-fingerprint",
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    # Outer transaction begins. Write A: a write entirely unrelated to
    # source registration (a second, independent ImportSession row),
    # staged in this same transaction but not yet committed.
    write_a = ImportSession(
        dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id, notes="write-A-must-survive"
    )
    db_session.add(write_a)
    await db_session.flush()
    write_a_id = write_a.id

    # Trigger the conflict path: a different identity for the same
    # session_id collides with the existing row's UNIQUE(import_session_id)
    # constraint, forcing the INSERT to fail and the CAS-UPDATE fallback to
    # resolve it -- the exact duplicate/conflict path PR90-H1 targets.
    conflicting_content = b"conflicting-bytes-different-from-existing"
    result, created = await import_crud.register_or_correct_source_pending(
        db_session,
        session_id=session_id,
        dataset_type=DATASET_TYPE,
        checksum=hashlib.sha256(conflicting_content).hexdigest(),
        byte_size=len(conflicting_content),
        content_type=None,
        filename=None,
        source_version=None,
    )
    assert created is False, "the conflicting insert must resolve via the CAS-UPDATE fallback, not report a fresh insert"

    # The caller's own pre-existing, uncommitted write must still be
    # visible in this same transaction -- proof the helper's internal
    # SAVEPOINT rollback was scoped to its own failed INSERT only, and
    # never terminated the caller's outer transaction.
    still_present = (
        await db_session.execute(select(ImportSession).where(ImportSession.id == write_a_id))
    ).scalar_one_or_none()
    assert still_present is not None, (
        "PR90-H1: a duplicate/conflict inside register_or_correct_source_pending must not roll back "
        "the caller's own unrelated prior write in the same transaction"
    )

    # The caller still owns the commit/rollback decision -- proven by
    # successfully committing here. A destroyed outer transaction (the
    # pre-fix bug) would have made this raise or silently lose write A.
    await db_session.commit()

    persisted_write_a = (
        await db_session.execute(select(ImportSession).where(ImportSession.id == write_a_id))
    ).scalar_one_or_none()
    assert persisted_write_a is not None, "write A must have survived the commit that followed the resolved conflict"
    assert persisted_write_a.notes == "write-A-must-survive"

    corrected_source = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == session_id))
    ).scalar_one()
    assert corrected_source.checksum == hashlib.sha256(conflicting_content).hexdigest()


def test_register_or_correct_source_pending_helper_never_calls_outer_rollback_or_commit():
    """AST-based static-inspection guard (not substring matching -- the
    function's own explanatory docstring legitimately mentions
    `db.rollback()`/`db.commit()` in prose, which a substring check would
    false-positive on): the helper must never contain an actual
    `db.rollback()`/`db.commit()` *call expression* -- only
    `db.begin_nested()`'s own SAVEPOINT-scoped `async with` block may issue
    transaction control."""
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(import_crud.register_or_correct_source_pending))
    tree = ast.parse(source)

    forbidden_calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("rollback", "commit")
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "db"
    ]
    assert forbidden_calls == [], (
        f"register_or_correct_source_pending must never call db.rollback()/db.commit() directly against the "
        f"caller's outer session, found call(s): {forbidden_calls}"
    )


# ---------------------------------------------------------------------------
# PR90-H2: multipart metadata (`source_version`, `content_type`) must be
# bounded at the API boundary -- matching `ImportSource.source_version`'s
# String(100) and `ImportSource.content_type`'s String(255) column widths
# -- and rejected there, never merely truncated or left for PostgreSQL to
# discover as a truncation/data error.
# ---------------------------------------------------------------------------


async def test_upload_source_version_at_max_length_is_accepted(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], source_version="v" * 100)
    assert resp.status_code == 201, resp.text
    assert resp.json()["source_version"] == "v" * 100


async def test_upload_source_version_over_max_length_rejected_before_persistence(
    client: AsyncClient, seeded_users, db_session
):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], source_version="v" * 101)
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"

    sources = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == uuid.UUID(session["id"])))
    ).scalars().all()
    assert sources == [], "an oversized source_version must be rejected before any registration write"
    assert (await db_session.execute(select(ImportSourceBlob))).scalars().all() == []


async def test_upload_content_type_at_max_length_is_accepted(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], content_type="a" * 255)
    assert resp.status_code == 201, resp.text
    assert resp.json()["content_type"] == "a" * 255


async def test_upload_content_type_over_max_length_rejected_before_persistence(
    client: AsyncClient, seeded_users, db_session
):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], content_type="a" * 256)
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == "INVALID_INPUT"

    sources = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == uuid.UUID(session["id"])))
    ).scalars().all()
    assert sources == [], "an oversized content_type must be rejected before any registration write"
    assert (await db_session.execute(select(ImportSourceBlob))).scalars().all() == []


async def test_upload_source_version_and_content_type_within_bounds_still_work_together(
    client: AsyncClient, seeded_users
):
    """Regression: the new bounds must not interfere with ordinary, in-range
    values -- both fields still round-trip correctly through the upload
    endpoint."""
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    resp = await _upload_source(client, headers, session["id"], source_version="rev-1", content_type="text/csv")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_version"] == "rev-1"
    assert body["content_type"] == "text/csv"
