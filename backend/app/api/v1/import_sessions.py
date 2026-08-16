import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, require_roles
from app.core.audit import AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CONFIRMED, AUDIT_ENTITY_IMPORT_SESSION, record_audit_event
from app.core.exceptions import (
    ImportDryRunPlanNotFoundError,
    ImportSessionNotFoundError,
    ImportSourceRegistrationMethodNotAllowedError,
    InvalidInputError,
)
from app.crud import import_dry_run_plan as import_dry_run_plan_crud
from app.crud import import_job as import_job_crud
from app.crud import import_session as import_crud
from app.crud import import_source_blob as import_source_blob_crud
from app.db.session import get_db
from app.models.import_session import ImportJob
from app.schemas.common import Page
from app.schemas.import_session import (
    DryRunPlanConfirmOut,
    DryRunPlanOut,
    DryRunPlanRowOut,
    DryRunPlanSummaryOut,
    ImportRetentionCleanupRequest,
    ImportRetentionCleanupResult,
    ImportSessionCreate,
    ImportSessionOut,
    ImportSessionStatusOut,
    ImportSessionSummaryOut,
    ImportSourceIn,
    ImportSourceOut,
    ValidationFindingOut,
)
from app.services import import_execution_service, import_retention_service, import_validation_service
from app.services.import_service import MAX_UPLOAD_BYTES, _read_upload_bounded, _validate_filename, _validate_zip_archive_bounds
from app.utils.pagination import decode_cursor, decode_int_cursor, encode_cursor, encode_int_cursor

# Roadmap PR20A (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §6.1,
# §6.2): the reserved dataset_type value this design owns. A plain literal
# (matching this codebase's existing convention for job_type/status
# literals, e.g. `import_execution_service._DRY_RUN_ALLOWED_FROM_STATUSES`)
# -- not a shared constant module, since the future EquipmentMasterAdapter
# (PR20C) declares its own `dataset_type` class attribute independently,
# per this codebase's existing ImportAdapter pattern.
_EQUIPMENT_MASTER_DATASET_TYPE = "equipment_master"

# PR90-H2: matches `ImportSource.content_type`'s exact column width
# (String(255), app/models/import_session.py), the same literal
# `ImportSourceIn.content_type`'s `Field(max_length=255)` already enforces
# for the metadata-only registration path (app/schemas/import_session.py).
# `UploadFile.content_type` is untrusted multipart metadata FastAPI does
# not itself bound the way it bounds a `Form(...)` field -- this endpoint
# must reject an oversized value itself, before any registration write,
# rather than letting it reach PostgreSQL and surface as a truncation/
# data error instead of a clean 400.
_CONTENT_TYPE_MAX_LENGTH = 255

# Roadmap PR19A1 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §21).
# Endpoints #1-#6: create, list, summary, status, source register/correct,
# cancel (PR19A1). Endpoints #7-#9 -- recover, validate, errors -- are
# Roadmap PR19A2's addition, including the lease/heartbeat/recovery/
# completion-fencing mechanism they depend on (see
# app.services.import_validation_service). Endpoints #10-#12 -- dry-run,
# execute, retention/cleanup -- are Roadmap PR19A3's addition (see
# app.services.import_execution_service / import_retention_service),
# composing onto PR19A2's mechanism unchanged rather than adding a new
# one (§25).

router = APIRouter(prefix="/import-sessions", tags=["import-sessions"])


async def _get_or_404(db: AsyncSession, session_id: uuid.UUID):
    session = await import_crud.get_by_id(db, session_id)
    if session is None:
        raise ImportSessionNotFoundError(f"Import session '{session_id}' not found.")
    return session


@router.post("", response_model=ImportSessionOut)
async def create_session(
    payload: ImportSessionCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session, created = await import_crud.get_or_create_session(
        db,
        dataset_type=payload.dataset_type,
        idempotency_key=payload.idempotency_key,
        notes=payload.notes,
        created_by_user_id=actor.id,
    )
    if created:
        await db.commit()
    # §15.1: 201 for a genuinely new session, 200 for an idempotent replay.
    response.status_code = 201 if created else 200
    return session


@router.get("", response_model=Page[ImportSessionOut])
async def list_sessions(
    dataset_type: str | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    cursor_dt = None
    cursor_uuid = None
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        try:
            cursor_uuid = uuid.UUID(cursor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise InvalidInputError("Invalid or malformed pagination cursor.") from exc

    rows, total = await import_crud.list_sessions(
        db, dataset_type=dataset_type, limit=limit, cursor_dt=cursor_dt, cursor_id=cursor_uuid
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
    return Page(items=rows, next_cursor=next_cursor, total=total)


@router.post("/retention/cleanup", response_model=ImportRetentionCleanupResult)
async def retention_cleanup(
    request: Request,
    payload: ImportRetentionCleanupRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    # §21 endpoint #12: registered ahead of the `/{session_id}` routes --
    # this path has no session id in it at all (a batch operation, not
    # scoped to one session), so there is no shape collision with any
    # `{session_id}/<literal>` route today, but registering it first
    # keeps that true defensively even if a future route's literal
    # second segment were ever named "cleanup".
    limit = payload.limit if payload is not None else 100
    result = await import_retention_service.run_retention_cleanup(db, actor_id=actor.id, request=request, limit=limit)
    return ImportRetentionCleanupResult(**result)


@router.get("/{session_id}", response_model=ImportSessionSummaryOut)
async def get_session_summary(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_or_404(db, session_id)
    jobs, finding_count = await import_crud.get_session_jobs_and_finding_count(db, session_id=session.id)
    return ImportSessionSummaryOut(
        **ImportSessionOut.model_validate(session).model_dump(),
        jobs=jobs,
        finding_count=finding_count,
        validation_attempt_id=session.current_validation_job_id,
    )


@router.get("/{session_id}/status", response_model=ImportSessionStatusOut)
async def get_session_status(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    return await _get_or_404(db, session_id)


@router.post("/{session_id}/source", response_model=ImportSourceOut)
async def register_source(
    session_id: uuid.UUID,
    payload: ImportSourceIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_or_404(db, session_id)
    # Roadmap PR20A (design §6.2, H2R2): a pure in-memory guard on the
    # already-loaded session's dataset_type -- no CRUD call, no database
    # write is reachable before this returns. Every other dataset_type
    # falls through to the existing handler body unchanged.
    if session.dataset_type == _EQUIPMENT_MASTER_DATASET_TYPE:
        raise ImportSourceRegistrationMethodNotAllowedError(
            "dataset_type 'equipment_master' does not accept metadata-only source registration. "
            "Use POST /import-sessions/{id}/source/upload instead."
        )
    source, created = await import_crud.register_or_correct_source(
        db,
        session_id=session.id,
        dataset_type=session.dataset_type,
        checksum=payload.checksum,
        byte_size=payload.byte_size,
        content_type=payload.content_type,
        filename=payload.filename,
        source_version=payload.source_version,
    )
    # §15.2/§21 endpoint #5: 201 for the session's first registration, 200
    # for an idempotent no-op or a pre-freeze correction.
    response.status_code = 201 if created else 200
    return source


@router.post("/{session_id}/source/upload", response_model=ImportSourceOut)
async def upload_source(
    session_id: uuid.UUID,
    response: Response,
    file: UploadFile = File(...),
    # Optional, advisory-only client-supplied checksum (design §6.2): the
    # server never trusts this as authority -- if supplied, it must match
    # the server's own independently computed checksum or the upload is
    # rejected as a client error, before any registration happens.
    checksum: str | None = Form(default=None),
    # PR90-H2: bounded to the exact `ImportSource.source_version` column
    # width (String(100), app/models/import_session.py) at the API
    # boundary -- an oversized value must be rejected by FastAPI/Pydantic's
    # own centralized RequestValidationError handling (app/main.py) before
    # this function body ever runs, never discovered only once it reaches
    # PostgreSQL. Mirrors `ImportSourceIn.source_version`'s identical
    # `Field(max_length=100)` bound on the existing metadata-only
    # registration path (app/schemas/import_session.py) -- the same
    # domain limit, enforced the same way, for both entry points.
    source_version: str | None = Form(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Roadmap PR20A (design §6.2): the single authoritative,
    server-checksummed registration operation. Step 1: bound-check the
    uploaded bytes (size/structure) -- no database writes yet. Step 2:
    compute the checksum/byte length server-side, from the actual received
    bytes. Step 3: persist the bytes durably and finalize the source's
    metadata together, as one physical database transaction (the
    non-committing CRUD variant + the blob upsert, committed once, here).
    A source can never reach a state where its metadata claims a
    checksum/byte length the actual durable blob does not match."""
    session = await _get_or_404(db, session_id)

    filename = _validate_filename(file.filename)
    if file.content_type is not None and len(file.content_type) > _CONTENT_TYPE_MAX_LENGTH:
        raise InvalidInputError(
            f"Uploaded file's content type exceeds the maximum allowed length of {_CONTENT_TYPE_MAX_LENGTH} characters."
        )
    content = await _read_upload_bounded(file, max_bytes=MAX_UPLOAD_BYTES)
    _validate_zip_archive_bounds(content)

    server_checksum = hashlib.sha256(content).hexdigest()
    if checksum is not None and checksum != server_checksum:
        raise InvalidInputError(
            "Supplied checksum does not match the server-computed checksum of the uploaded bytes."
        )

    source, created = await import_crud.register_or_correct_source_pending(
        db,
        session_id=session.id,
        dataset_type=session.dataset_type,
        checksum=server_checksum,
        byte_size=len(content),
        content_type=file.content_type,
        filename=filename,
        source_version=source_version,
    )
    await import_source_blob_crud.upsert_pending(db, import_source_id=source.id, content=content)
    await db.commit()

    response.status_code = 201 if created else 200
    return source


@router.post("/{session_id}/cancel", response_model=ImportSessionOut)
async def cancel_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_or_404(db, session_id)
    return await import_crud.cancel_session(db, session_id=session.id, expected_version=session.version)


@router.post("/{session_id}/recover", response_model=ImportSessionOut)
async def recover_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_or_404(db, session_id)
    return await import_validation_service.recover_session(db, session=session, actor_id=actor.id, request=request)


@router.post("/{session_id}/validate", response_model=ImportSessionOut)
async def validate_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_or_404(db, session_id)
    return await import_validation_service.run_validation(db, session=session, actor_id=actor.id, request=request)


@router.post("/{session_id}/dry-run", response_model=ImportSessionOut)
async def dry_run_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_or_404(db, session_id)
    return await import_execution_service.run_dry_run(db, session=session, actor_id=actor.id, request=request)


@router.post("/{session_id}/execute", response_model=ImportSessionOut)
async def execute_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_or_404(db, session_id)
    return await import_execution_service.run_execute(db, session=session, actor_id=actor.id, request=request)


@router.get("/{session_id}/dry-run-plan", response_model=DryRunPlanOut)
async def get_dry_run_plan(
    session_id: uuid.UUID,
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Roadmap PR20D (design §14.6). Resolves the session's current
    `active` plan (never a client-supplied plan id -- there is no
    "dry-run-summary recompute" endpoint, §24) and returns its persisted
    identity/summary plus a paginated slice of its rows. `404
    IMPORT_DRY_RUN_PLAN_NOT_FOUND` if the session has never had a
    successful dry-run."""
    session = await _get_or_404(db, session_id)
    plan = await import_dry_run_plan_crud.get_current_plan(db, import_session_id=session.id)
    if plan is None:
        raise ImportDryRunPlanNotFoundError(f"Import session '{session_id}' has no persisted dry-run plan.")

    cursor_n = None
    cursor_uuid = None
    if cursor:
        cursor_n, cursor_id = decode_int_cursor(cursor)
        try:
            cursor_uuid = uuid.UUID(cursor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise InvalidInputError("Invalid or malformed pagination cursor.") from exc

    rows, total = await import_dry_run_plan_crud.list_plan_rows(
        db, plan_id=plan.id, limit=limit, cursor_n=cursor_n, cursor_id=cursor_uuid
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_int_cursor(last.source_row_number, str(last.id))

    return DryRunPlanOut(
        id=plan.id,
        import_session_id=plan.import_session_id,
        import_source_id=plan.import_source_id,
        status=plan.status,
        is_current=plan.status == "active",
        created_at=plan.created_at,
        confirmed_at=plan.confirmed_at,
        confirmed_by_user_id=plan.confirmed_by_user_id,
        summary=DryRunPlanSummaryOut(
            total_rows=plan.summary_total_rows,
            creates=plan.summary_creates,
            updates=plan.summary_updates,
            skips=plan.summary_skips,
            warnings=plan.summary_warnings,
            blocking_conflicts=plan.summary_blocking_conflicts,
        ),
        rows=[DryRunPlanRowOut.model_validate(row) for row in rows],
        rows_next_cursor=next_cursor,
        rows_total=total,
    )


@router.post("/{session_id}/dry-run-plan/{plan_id}/confirm", response_model=DryRunPlanConfirmOut)
async def confirm_dry_run_plan(
    session_id: uuid.UUID,
    plan_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Roadmap PR20D (design §14.4a). The explicit operator confirmation
    step -- PR20E's `execute()` will only ever apply a plan that reached
    this state.

    Fix round 2 (PR94-H1/H2/M1): `app.crud.import_dry_run_plan.confirm_plan`
    now locks the `ImportSession` row then the plan row (in that order,
    matching `persist_dry_run_plan`'s own lock order -- see that
    function's docstring) before its conditional `UPDATE`, so this call
    genuinely serializes against a concurrent `cancel_session` or new
    dry-run admission instead of racing an unlocked read against their
    writes. It raises directly rather than returning `None`:
    `ImportSessionNotFoundError` (`404`, unknown session id) or
    `ImportDryRunPlanNotFoundError` (`404`, wrong/foreign plan id).

    Fix round 4 (PR20 design §14.4a, fix round 8/M4): every other
    plan-invalidating condition -- the plan no longer `active`
    (superseded/consumed/failed), *and* the owning session no longer
    `dry_run_completed` (a concurrent cancel or new dry-run won the race)
    -- raises the SAME `ImportDryRunPlanStaleError` (`409
    IMPORT_DRY_RUN_PLAN_STALE`). The design doc is explicit that this
    endpoint's stale-plan contract does not distinguish these sub-cases
    with different codes; all of them mean the same thing to the client:
    re-fetch `GET .../dry-run-plan` and re-check before confirming again.
    `IMPORT_SESSION_INVALID_STATE` remains reserved for endpoints whose
    operation is not "confirm this specific persisted plan" (e.g.
    `cancel_session`'s own CAS rejection) -- never for this endpoint.

    The `CONFIRMED` audit event is written only when
    `result.newly_confirmed` -- a repeat confirm (same user retry, a
    second user's idempotent re-confirm, or a network retry after a lost
    response) is reported as the same success but never produces a second
    audit row, and never re-attributes the persisted `confirmed_by_user_id`
    away from the original first confirmer. The response's `summary` is
    the plan's own persisted summary (`result.plan`), never recomputed."""
    session = await _get_or_404(db, session_id)
    result = await import_dry_run_plan_crud.confirm_plan(
        db, plan_id=plan_id, import_session_id=session.id, current_user_id=actor.id
    )
    if result.newly_confirmed:
        await record_audit_event(
            db,
            actor_user_id=actor.id,
            action=AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CONFIRMED,
            entity_type=AUDIT_ENTITY_IMPORT_SESSION,
            entity_id=session.id,
            after={
                "dry_run_plan_id": str(result.plan.id),
                "confirmed_at": result.plan.confirmed_at.isoformat() if result.plan.confirmed_at else None,
            },
            request=request,
        )
    await db.commit()
    plan = result.plan
    return DryRunPlanConfirmOut(
        id=plan.id,
        import_session_id=plan.import_session_id,
        status=plan.status,
        confirmed_at=plan.confirmed_at,
        confirmed_by_user_id=plan.confirmed_by_user_id,
        summary=DryRunPlanSummaryOut(
            total_rows=plan.summary_total_rows,
            creates=plan.summary_creates,
            updates=plan.summary_updates,
            skips=plan.summary_skips,
            warnings=plan.summary_warnings,
            blocking_conflicts=plan.summary_blocking_conflicts,
        ),
    )


@router.get("/{session_id}/errors", response_model=Page[ValidationFindingOut])
async def list_validation_errors(
    session_id: uuid.UUID,
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    attempt_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_or_404(db, session_id)

    # §12: defaults to the current promoted attempt; ?attempt_id= selects a
    # historical one instead. A caller-supplied attempt_id that doesn't
    # exist, or belongs to a different session, or isn't a validate job, is
    # an invalid reference -- never silently ignored or leaked across
    # sessions (relation/ownership check).
    if attempt_id is not None:
        job = (await db.execute(select(ImportJob).where(ImportJob.id == attempt_id))).scalar_one_or_none()
        if job is None or job.import_session_id != session.id or job.job_type != "validate":
            raise InvalidInputError("attempt_id does not reference a validate attempt belonging to this session.")
        job_id = job.id
    elif session.current_validation_job_id is not None:
        job_id = session.current_validation_job_id
    else:
        return Page(items=[], next_cursor=None, total=0)

    cursor_n = None
    cursor_uuid = None
    if cursor:
        cursor_n, cursor_id = decode_int_cursor(cursor)
        try:
            cursor_uuid = uuid.UUID(cursor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise InvalidInputError("Invalid or malformed pagination cursor.") from exc

    rows, total = await import_job_crud.list_findings(db, job_id=job_id, limit=limit, cursor_n=cursor_n, cursor_id=cursor_uuid)
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        last_sort_value = last.row_number if last.row_number is not None else import_job_crud.MAX_ROW_NUMBER_SORT_VALUE
        next_cursor = encode_int_cursor(last_sort_value, str(last.id))
    return Page(items=rows, next_cursor=next_cursor, total=total)
