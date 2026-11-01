"""Roadmap PR21D1 -- Combined Canonical Adapter + Source Admission.

Composes the already-merged, independently-tested PR21B Issue parser
(`issue.py`, GitHub PR #104) and PR21C Receive parser (`receive.py`,
GitHub PR #105) into the production `ImportAdapter` for
`legacy_transaction_history`, authorized by Owner Decision Closure
Round 3 (GitHub PR #106, design doc §55.2/§55.8) now that SDC is
excluded from PR21 V1 scope (§6.5).

**Topology (§13 of the PR21D1 task, design doc §55.3):** one workbook
snapshot -> one `ImportSession` -> one `ImportSource` -> all four
canonical sheets validated together, one aggregate all-or-nothing
decision. This module never creates a separate Issue-only or
Receive-only session/source, and never produces a partial plan
containing only the passing side.

**No duplication of Issue/Receive business validation (§6 of the task).**
This module calls `issue.parse_workbook`/`issue.preload_business_context`/
`issue.validate_and_build_candidates` and the Receive-side equivalents
completely unchanged -- no per-row validation logic is reimplemented
here. The one accepted performance trade-off (§7 of the task): the
workbook is decompressed/loaded twice (once by `issue.parse_workbook`,
once by `receive.parse_workbook`), each already independently secured
(macro/zip-bomb/worksheet-count bounds, `common.load_workbook_bytes`).
Sharing one loaded `Workbook` between both parsers would require
invasive changes to both already-tested modules for a ~20MB file's
second decompression pass; per the task's own explicit permission
("keep correctness first and document performance trade-off"), this
slice keeps the two proven parsers untouched rather than risk that
refactor.

**No Issue<->Receive pairing (§4/§55.4).** Candidates from both sides
are validated, and later persisted as dry-run plan rows, entirely
independently -- neither module is ever handed the other's records or
candidates. PR22-or-later owns reconciliation.

**No `LegacyEquipmentEvent` execution (§21/§55.5, §60/§61).** This
adapter deliberately does not override `execute()`/`precheck_execute()`/
`on_execution_success`/`on_execution_failure`/`on_execution_recovery` --
the `ImportAdapter` base class's own defaults (`execute()` raises
`NotImplementedError`; the others are safe no-ops) apply unchanged, so
`import_execution_service.run_execute`'s own
`type(adapter).execute is ImportAdapter.execute` guard (mirroring the
identical guard `run_dry_run` already applies to `plan_dry_run`) keeps
`POST .../execute` structurally unreachable for this dataset_type until
a future PR21D2 slice deliberately overrides `execute()`. No production
path from this adapter alone can ever insert a `LegacyEquipmentEvent`
row.

**Where the checksum/migration-authority gate is actually enforced.**
`parse()` is synchronous and CPU-bound (no database access, by the
`ImportAdapter` contract); `preload_business_context()` receives a `db`
session but -- per `app.services.import_adapter_context`'s own
docstring -- the validate phase (`import_validation_service.
run_validation`) never populates `AdapterInvocationContext`, so neither
method has access to the active `ImportSource`'s checksum. This means
the checksum/authority gate cannot run during `validate` -- only
per-row `FieldError` findings are ever produced there, never a typed
`LegacyIssueCandidate`/`LegacyReceiveCandidate`. The gate runs in
`plan_dry_run()`, which *does* receive `AdapterInvocationContext`
(including `source_checksum`) via `get_adapter_invocation_context()`:
no candidate is ever constructed, and no `LegacyHistoryDryRunPlan` is
ever created, unless a `LegacyMigrationAuthority` row exists whose
`approved_workbook_sha256` exactly matches the active source's
checksum. This still satisfies the "a validated candidate must never
be produced under an authority mismatch" invariant precisely, since no
candidate exists before `plan_dry_run` runs -- see this PR's own final
report for the full explanation and the discovered gap this implies
(no Administrator-facing workflow yet exists to create the first
`LegacyMigrationAuthority` row in production)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import (
    AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CREATED,
    AUDIT_ENTITY_IMPORT_SESSION,
    record_audit_event,
)
from app.core.exceptions import ImportNoConfirmedPlanError, InvalidInputError
from app.crud import legacy_equipment_event as legacy_equipment_event_crud
from app.crud import legacy_history_dry_run_plan as legacy_history_dry_run_plan_crud
from app.crud import legacy_migration_authority as legacy_migration_authority_crud
from app.models.import_session import ImportSession
from app.models.legacy_history import LegacyEquipmentEvent, LegacyEquipmentEventSourceRef, LegacyHistoryDryRunPlanRow
from app.services.import_adapter import (
    AdapterExecutionConflict,
    DryRunPlan,
    FieldError,
    ImportAdapter,
    RawImportRecord,
    register_adapter,
)
from app.services.import_adapter_context import get_adapter_invocation_context, record_resolved_execution_resource
from app.services.import_adapters.legacy_history import common, issue, receive
from app.services.import_plan_providers.legacy_history import DATASET_TYPE
from app.services.import_source_reader import VerifiedSourceContent

# §9 of the task: dataset-specific selection happens in the upload
# endpoint (`app.api.v1.import_sessions.upload_source`), keyed off this
# exact `dataset_type` string -- never a client-supplied value.
_KIND_ISSUE_HEADER = "issue_header"
_KIND_ISSUE_LINE = "issue_line"
_KIND_RECEIVE_HEADER = "receive_header"
_KIND_RECEIVE_LINE = "receive_line"

_KIND_SHEET_NAME: dict[str, str] = {
    _KIND_ISSUE_HEADER: issue.HEADER_SHEET_NAME,
    _KIND_ISSUE_LINE: issue.LINE_SHEET_NAME,
    _KIND_RECEIVE_HEADER: receive.HEADER_SHEET_NAME,
    _KIND_RECEIVE_LINE: receive.LINE_SHEET_NAME,
}

# §55.2/§9 of the task: used only to call `validate_and_build_candidates`
# during the identity-blind validate phase, purely to extract findings --
# never persisted, never attached to a real candidate. See this module's
# own docstring ("Where the checksum/migration-authority gate is actually
# enforced") for why real identity is unavailable here at all.
_PLACEHOLDER_ID = uuid.UUID(int=0)

# Roadmap PR21D2 (design §24): bounds how many new
# `LegacyEquipmentEvent`/`LegacyEquipmentEventSourceRef` ORM objects
# `execute()` accumulates before flushing, keeping SQLAlchemy session
# memory and any one INSERT statement's bind-parameter count bounded
# regardless of how large the confirmed plan is (up to
# `common.PR21_MAX_IMPORT_RECORDS`).
_EXECUTE_BATCH_SIZE = 1000


class _LegacyEventIdentityConflictError(RuntimeError):
    """Roadmap PR21D2 (design §9/§33): the structured internal signal for
    a proven historical-event identity conflict -- a plan row's identity
    `(migration_authority_id, event_type, legacy_source_row_key)` already
    exists in the database, but the persisted immutable fact (or its
    provenance) does not match the current approved plan's own value.
    Always caught and converted to `AdapterExecutionConflict` before
    leaving `LegacyTransactionHistoryAdapter._apply_plan_rows` -- this
    message deliberately carries no raw workbook content (never
    `legacy_ward_text`/`legacy_bme_name`/`legacy_order_reference`), only
    structural identifiers, per the task's own "no sensitive source
    content in error messages" instruction."""

    def __init__(self, *, event_type: str, legacy_source_row_key: str) -> None:
        super().__init__(
            f"Historical event identity conflict for event_type={event_type!r}, "
            f"legacy_source_row_key={legacy_source_row_key!r}: a previously-persisted event exists under "
            "this migration authority whose immutable fact does not match the currently approved plan."
        )
        self.event_type = event_type
        self.legacy_source_row_key = legacy_source_row_key


def _plan_row_matches_existing_event(existing: "LegacyEquipmentEvent", normalized_values: dict) -> bool:
    """§10 of the PR21D2 task's exact equivalence set (excluding the
    provenance-identity bullet, checked separately by
    `LegacyTransactionHistoryAdapter._existing_event_provenance_matches_plan`
    since it requires a database read): `equipment_id`, `occurred_at`,
    `legacy_order_reference`, `legacy_ward_text`, `resolved_ward_id`,
    `legacy_bme_name`. `migration_authority_id`/`event_type`/
    `legacy_source_row_key` are the identity tuple itself (already equal
    by construction of the caller's lookup) and are not re-compared
    here. Deliberately never compares `หมายเหตุ`/notes or any other field
    outside this exact set -- no such field exists on this model at all
    (OD-PR21-6, unchanged)."""
    try:
        expected_equipment_id = uuid.UUID(normalized_values["equipment_id"])
        expected_occurred_at = datetime.fromisoformat(normalized_values["occurred_at"])
    except (KeyError, ValueError):
        return False
    expected_ward_raw = normalized_values.get("resolved_ward_id")
    expected_ward_id = uuid.UUID(expected_ward_raw) if expected_ward_raw else None
    return (
        existing.equipment_id == expected_equipment_id
        and existing.occurred_at == expected_occurred_at
        and existing.legacy_order_reference == normalized_values.get("legacy_order_reference")
        and existing.legacy_ward_text == normalized_values.get("legacy_ward_text")
        and existing.resolved_ward_id == expected_ward_id
        and existing.legacy_bme_name == normalized_values.get("legacy_bme_name")
    )


@dataclass(frozen=True)
class _CombinedValidationContext:
    findings_by_row_number: dict[int, list[FieldError]] = field(default_factory=dict)


def _finding_to_field_error(finding) -> FieldError:
    """Converts a rich `LegacyIssueFinding`/`LegacyReceiveFinding` (which
    carries `sheet_name` -- a concept the generic `ImportRowError` model
    has no column for, §15 of the task) into the generic `FieldError`
    shape without discarding sheet identity: `field` is prefixed with
    the sheet name, and `message` is prefixed with `"{sheet} row {n}:
    "`, so both survive in the existing `field`/`message` columns rather
    than requiring a schema change (§51 of the task: no migration
    expected in this slice)."""
    field_name = f"{finding.sheet_name}:{finding.field}" if finding.field else finding.sheet_name
    message = f"{finding.sheet_name} row {finding.source_row_number}: {finding.message}"
    return FieldError(field=field_name[:100], error_code=finding.error_code, message=message, severity=finding.severity)


def _candidate_to_row_dict(candidate) -> dict[str, Any]:
    """One `LegacyHistoryDryRunPlanRow`-shaped dict per candidate (§18 of
    the task: preserves everything PR21D2 will need to execute without
    re-resolving -- event_type, source row key, order reference,
    equipment_id, occurred_at, raw Ward text, resolved Ward id, raw BME
    text, and both source coordinates). `หมายเหตุ`/notes never appear on
    `LegacyIssueCandidate`/`LegacyReceiveCandidate` in the first place
    (OD-PR21-6, unchanged) -- there is nothing to redact here."""
    return {
        "source_row_number": candidate.line_source_ref.source_row_number,
        "event_type": candidate.event_type,
        "legacy_source_row_key": candidate.legacy_source_row_key,
        "normalized_values": {
            "legacy_order_reference": candidate.legacy_order_reference,
            "equipment_id": str(candidate.equipment_id),
            "occurred_at": candidate.occurred_at.isoformat(),
            "legacy_ward_text": candidate.legacy_ward_text,
            "resolved_ward_id": str(candidate.resolved_ward_id) if candidate.resolved_ward_id else None,
            "legacy_bme_name": candidate.legacy_bme_name,
            "header_source_ref": {
                "sheet_name": candidate.header_source_ref.sheet_name,
                "source_row_number": candidate.header_source_ref.source_row_number,
            },
            "line_source_ref": {
                "sheet_name": candidate.line_source_ref.sheet_name,
                "source_row_number": candidate.line_source_ref.source_row_number,
            },
        },
        "warnings": [],
    }


class LegacyTransactionHistoryAdapter(ImportAdapter):
    dataset_type = DATASET_TYPE
    ruleset_version = "1"
    # PR21D1 fix (P1 review, GitHub PR #107): see `common.PR21_MAX_IMPORT_
    # RECORDS`'s own docstring for the exact evidence-derived combined
    # record count this bounds against and why 5,000 (the framework's
    # generic `ImportAdapter.max_import_rows` default) cannot admit the
    # real approved workbook.
    max_import_rows = common.PR21_MAX_IMPORT_RECORDS

    def parse(self, raw_input: Any) -> list[RawImportRecord]:
        """§2/§6 of the task: loads the workbook once per canonical side
        (via the unchanged `issue.parse_workbook`/`receive.parse_workbook`),
        then flattens all four record lists (Issue header, Issue line,
        Receive header, Receive line) into one combined list with a
        synthetic, globally-unique `row_number` -- the generic
        `ImportAdapter` contract has no concept of multiple sheets
        sharing one row-number space (§15 of the task), so a single
        linear numbering is assigned here, in this fixed, deterministic
        order, purely for the framework's own row bookkeeping
        (`MAX_IMPORT_ROWS`, `ImportRowError.row_number`). Each combined
        record's original per-role fields are preserved unchanged
        (`_kind`/`_source_row_number` are the only additions), so
        `preload_business_context` below can reconstruct the exact
        original `RawImportRecord` objects `issue.py`/`receive.py`
        expect, byte-for-byte."""
        if not isinstance(raw_input, VerifiedSourceContent):
            raise InvalidInputError(
                "legacy_transaction_history import requires a verified, byte-backed source; "
                "none was supplied for this session."
            )
        content = raw_input.content
        # Defense-in-depth re-check (mirrors `EquipmentMasterAdapter.parse`'s
        # identical pattern) -- the upload endpoint already enforces
        # `PR21_MAX_UPLOAD_BYTES` before storage, this re-checks the
        # stored content at read time.
        if len(content) > common.PR21_MAX_UPLOAD_BYTES:
            raise InvalidInputError(
                f"Stored source content exceeds the maximum allowed size of "
                f"{common.PR21_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            )

        issue_header_records, issue_line_records = issue.parse_workbook(content)
        receive_header_records, receive_line_records = receive.parse_workbook(content)

        combined: list[RawImportRecord] = []
        idx = 0
        for kind, source_records in (
            (_KIND_ISSUE_HEADER, issue_header_records),
            (_KIND_ISSUE_LINE, issue_line_records),
            (_KIND_RECEIVE_HEADER, receive_header_records),
            (_KIND_RECEIVE_LINE, receive_line_records),
        ):
            for rec in source_records:
                idx += 1
                fields = dict(rec.fields)
                fields["_kind"] = kind
                fields["_source_row_number"] = rec.row_number
                combined.append(RawImportRecord(row_number=idx, fields=fields))
        return combined

    async def preload_business_context(
        self, db: AsyncSession, records: list[RawImportRecord]
    ) -> _CombinedValidationContext:
        """Reconstructs the four original per-sheet record lists from
        the combined/flattened list `parse()` produced, then delegates
        entirely to `issue.preload_business_context`/
        `issue.validate_and_build_candidates` and the Receive-side
        equivalents (§6 of the task: no duplicated business logic).
        `validate_and_build_candidates` is called once per side here
        using a placeholder identity (`_PLACEHOLDER_ID`) purely to
        extract findings -- the validate phase has no real session/
        source identity available (see this module's own docstring);
        the returned candidates are discarded, never persisted, never
        exposed to a caller. Findings are re-keyed from their true
        `(sheet_name, source_row_number)` back onto this call's own
        synthetic row numbering, so `validate_business_rules` below can
        look them up by the same `record.row_number` the framework
        already has in hand -- one bulk pass, no per-record query."""
        synthetic_by_true: dict[tuple[str, int], int] = {}
        issue_header_records: list[RawImportRecord] = []
        issue_line_records: list[RawImportRecord] = []
        receive_header_records: list[RawImportRecord] = []
        receive_line_records: list[RawImportRecord] = []

        for rec in records:
            kind = rec.fields["_kind"]
            source_row_number = rec.fields["_source_row_number"]
            sheet_name = _KIND_SHEET_NAME[kind]
            synthetic_by_true[(sheet_name, source_row_number)] = rec.row_number
            inner_fields = {k: v for k, v in rec.fields.items() if k not in ("_kind", "_source_row_number")}
            inner_record = RawImportRecord(row_number=source_row_number, fields=inner_fields)
            if kind == _KIND_ISSUE_HEADER:
                issue_header_records.append(inner_record)
            elif kind == _KIND_ISSUE_LINE:
                issue_line_records.append(inner_record)
            elif kind == _KIND_RECEIVE_HEADER:
                receive_header_records.append(inner_record)
            else:
                receive_line_records.append(inner_record)

        issue_context = await issue.preload_business_context(db, issue_header_records, issue_line_records)
        receive_context = await receive.preload_business_context(db, receive_header_records, receive_line_records)

        _issue_candidates, issue_findings = issue.validate_and_build_candidates(
            issue_header_records,
            issue_line_records,
            issue_context,
            migration_authority_id=_PLACEHOLDER_ID,
            import_session_id=_PLACEHOLDER_ID,
            import_source_id=_PLACEHOLDER_ID,
        )
        _receive_candidates, receive_findings = receive.validate_and_build_candidates(
            receive_header_records,
            receive_line_records,
            receive_context,
            migration_authority_id=_PLACEHOLDER_ID,
            import_session_id=_PLACEHOLDER_ID,
            import_source_id=_PLACEHOLDER_ID,
        )

        # Deterministic ordering (§15/§23 of the task): Issue header,
        # Issue line, Receive header, Receive line findings, in the
        # exact order each side's own `validate_and_build_candidates`
        # already returns them (itself deterministic, PR21B/C §34).
        findings_by_row_number: dict[int, list[FieldError]] = {}
        for finding in (*issue_findings, *receive_findings):
            synthetic_row = synthetic_by_true.get((finding.sheet_name, finding.source_row_number))
            if synthetic_row is None:  # pragma: no cover -- structurally unreachable, see docstring
                continue
            findings_by_row_number.setdefault(synthetic_row, []).append(_finding_to_field_error(finding))

        return _CombinedValidationContext(findings_by_row_number=findings_by_row_number)

    def validate_business_rules(self, record: RawImportRecord, context: object) -> list[FieldError]:
        assert isinstance(context, _CombinedValidationContext)
        return context.findings_by_row_number.get(record.row_number, [])

    async def plan_dry_run(self, db: AsyncSession) -> DryRunPlan:
        """Re-runs the full parse/preload/validate pass against the
        current database state (mirrors `EquipmentMasterAdapter.
        plan_dry_run`'s own established pattern) -- this time with real
        identity available via `get_adapter_invocation_context()`, so
        real `LegacyIssueCandidate`/`LegacyReceiveCandidate` objects are
        built. §55.3/§14 of the task's all-or-nothing invariant: any
        blocking finding on *either* side at this re-validation means
        the whole dry-run fails -- raising here (rather than returning a
        partial plan) routes through the same TX1/TX2 fenced-failure
        path `run_validation` already uses, landing the session in
        `dry_run_failed`, never a plan containing only the passing
        side's rows."""
        ctx = get_adapter_invocation_context()
        if ctx.verified_source_content is None:
            raise InvalidInputError(
                "legacy_transaction_history dry-run requires a verified, byte-backed source; "
                "none was supplied for this session."
            )
        content = ctx.verified_source_content.content

        # §11/§55.6 of the task: the checksum/authority gate. See this
        # module's own docstring for why this is the first point at
        # which it can run.
        authority = await legacy_migration_authority_crud.get_by_checksum(
            db, approved_workbook_sha256=ctx.source_checksum
        )
        if authority is None:
            raise InvalidInputError(
                "No approved LegacyMigrationAuthority exists for this source's checksum; the active "
                "workbook cannot be admitted to a PR21 dry-run until an Administrator explicitly "
                "approves it as a migration authority."
            )

        issue_header_records, issue_line_records = issue.parse_workbook(content)
        receive_header_records, receive_line_records = receive.parse_workbook(content)
        issue_context = await issue.preload_business_context(db, issue_header_records, issue_line_records)
        receive_context = await receive.preload_business_context(db, receive_header_records, receive_line_records)

        issue_candidates, issue_findings = issue.validate_and_build_candidates(
            issue_header_records,
            issue_line_records,
            issue_context,
            migration_authority_id=authority.id,
            import_session_id=ctx.import_session_id,
            import_source_id=ctx.import_source_id,
        )
        receive_candidates, receive_findings = receive.validate_and_build_candidates(
            receive_header_records,
            receive_line_records,
            receive_context,
            migration_authority_id=authority.id,
            import_session_id=ctx.import_session_id,
            import_source_id=ctx.import_source_id,
        )

        blocking_count = sum(1 for f in issue_findings if f.severity == "error") + sum(
            1 for f in receive_findings if f.severity == "error"
        )
        if blocking_count:
            raise InvalidInputError(
                f"Re-validation at dry-run time found {blocking_count} blocking finding(s) across the "
                "Issue/Receive canonical sheets; no dry-run plan can be created while either side has "
                "an unresolved error."
            )

        rows = [_candidate_to_row_dict(c) for c in issue_candidates] + [
            _candidate_to_row_dict(c) for c in receive_candidates
        ]
        summary = {
            "rows": rows,
            "issue_events": len(issue_candidates),
            "receive_events": len(receive_candidates),
            "warnings": 0,
            "blocking_conflicts": 0,
            "migration_authority_id": str(authority.id),
        }
        return DryRunPlan(summary=summary)

    async def persist_dry_run_plan(self, db: AsyncSession, plan: DryRunPlan) -> None:
        """Mirrors `EquipmentMasterAdapter.persist_dry_run_plan`'s own
        Session-then-Plan lock order exactly (that method's own
        docstring explains why -- avoiding a lock-order deadlock against
        a concurrent `confirm_plan` call, which locks Session-then-Plan
        too)."""
        ctx = get_adapter_invocation_context()
        summary = plan.summary
        rows_data: list[dict[str, Any]] = summary.get("rows", [])
        migration_authority_id = uuid.UUID(summary["migration_authority_id"])

        session_lock_stmt = select(ImportSession.id).where(ImportSession.id == ctx.import_session_id)
        if db.get_bind().dialect.name == "postgresql":
            session_lock_stmt = session_lock_stmt.with_for_update()
        await db.execute(session_lock_stmt)

        await legacy_history_dry_run_plan_crud.supersede_active_plan(db, import_session_id=ctx.import_session_id)
        plan_row = await legacy_history_dry_run_plan_crud.insert_plan(
            db,
            import_session_id=ctx.import_session_id,
            import_source_id=ctx.import_source_id,
            migration_authority_id=migration_authority_id,
            source_checksum=ctx.source_checksum,
            accepted_validation_job_id=ctx.accepted_validation_job_id,
            dry_run_job_id=ctx.dry_run_job_id,
            ruleset_version=ctx.ruleset_version,
            summary_total_rows=summary["issue_events"] + summary["receive_events"],
            summary_issue_events=summary["issue_events"],
            summary_receive_events=summary["receive_events"],
            summary_warnings=summary["warnings"],
            summary_blocking_conflicts=summary["blocking_conflicts"],
        )

        row_models = [
            LegacyHistoryDryRunPlanRow(
                dry_run_plan_id=plan_row.id,
                source_row_number=row["source_row_number"],
                event_type=row["event_type"],
                legacy_source_row_key=row["legacy_source_row_key"],
                normalized_values=row["normalized_values"],
                warnings=row["warnings"],
            )
            for row in rows_data
        ]
        await legacy_history_dry_run_plan_crud.bulk_insert_plan_rows(db, row_models)

        # §40 of the task: no raw notes content anywhere -- normalized_values
        # never carries a notes field (see `_candidate_to_row_dict`), and
        # nothing below references one either.
        await record_audit_event(
            db,
            actor_user_id=ctx.actor_user_id,
            action=AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CREATED,
            entity_type=AUDIT_ENTITY_IMPORT_SESSION,
            entity_id=ctx.import_session_id,
            after={
                "dry_run_plan_id": str(plan_row.id),
                "import_source_id": str(ctx.import_source_id),
                "source_checksum": ctx.source_checksum,
                "migration_authority_id": str(migration_authority_id),
                "summary_total_rows": plan_row.summary_total_rows,
                "summary_issue_events": plan_row.summary_issue_events,
                "summary_receive_events": plan_row.summary_receive_events,
            },
        )

    async def precheck_execute(self, db: AsyncSession) -> None:
        """Roadmap PR21D2 (design §21, mirrors `EquipmentMasterAdapter.
        precheck_execute`'s own established pattern exactly). A read-only
        rejection, called strictly before `admit_phase_job` -- a session
        with no confirmed plan never has any state touched at all."""
        ctx = get_adapter_invocation_context()
        plan = await legacy_history_dry_run_plan_crud.get_active_confirmed_for_session(
            db, import_session_id=ctx.import_session_id
        )
        if plan is None:
            raise ImportNoConfirmedPlanError(
                f"Import session '{ctx.import_session_id}' has no confirmed dry-run plan to execute. "
                "Confirm the current plan (POST .../dry-run-plan/{plan_id}/confirm) first."
            )

    async def execute(self, db: AsyncSession) -> int:
        """Roadmap PR21D2 (design §5-§9, §22). Resolves the session's
        `active`, confirmed plan internally -- exactly like
        `precheck_execute` above -- never from a client-supplied plan id
        (§6 of the task). Re-verifies the plan's own frozen source/
        authority binding (§7) before writing a single row: the plan's
        `import_source_id`/`source_checksum` must match this invocation's
        own frozen context, and the `LegacyMigrationAuthority` currently
        bound to that checksum must be the exact same authority the plan
        itself already carries -- never a caller-substituted id.

        Delegates the actual per-row insert/idempotency work to
        `_apply_plan_rows` (below). Any conflict there -- an identity
        collision whose stored fact disagrees with the plan, a database
        constraint violation, or any other exception -- raises
        `AdapterExecutionConflict` carrying the resolved plan's own id,
        so the framework's TX2 failure path can mark the plan `failed`
        using only that primitive. Never calls `db.commit()`/
        `db.rollback()` itself -- the caller's TX1 owns the transaction
        boundary: if any row conflicts, the ENTIRE attempt rolls back,
        never partially applying the other, non-conflicting rows (§18 of
        the task, the same all-or-nothing contract `EquipmentMasterAdapter.
        execute()` already established for this framework)."""
        ctx = get_adapter_invocation_context()
        plan = await legacy_history_dry_run_plan_crud.get_active_confirmed_for_session(
            db, import_session_id=ctx.import_session_id
        )
        if plan is None:
            raise AdapterExecutionConflict(
                f"Import session '{ctx.import_session_id}' has no confirmed active plan at execute time "
                "despite precheck_execute succeeding -- a framework-invariant violation.",
                resolved_resource_id=None,
            )
        # Captured as a primitive immediately, before any write is
        # attempted -- mirrors EquipmentMasterAdapter.execute()'s own
        # documented rationale (a failed flush aborts the whole
        # PostgreSQL transaction, expiring every loaded ORM attribute).
        plan_id = plan.id
        record_resolved_execution_resource(plan_id)

        # §7 of the task: source/authority binding, re-verified here --
        # structurally guaranteed by the frozen-once-registered source
        # contract, but checked, not assumed.
        if plan.import_source_id != ctx.import_source_id or plan.source_checksum != ctx.source_checksum:
            raise AdapterExecutionConflict(
                f"Persisted plan '{plan_id}' source binding does not match the current session's frozen source.",
                resolved_resource_id=plan_id,
            )
        authority = await legacy_migration_authority_crud.get_by_checksum(
            db, approved_workbook_sha256=ctx.source_checksum
        )
        if authority is None or authority.id != plan.migration_authority_id:
            raise AdapterExecutionConflict(
                f"Persisted plan '{plan_id}' migration authority binding no longer matches the current "
                "source checksum's approved authority.",
                resolved_resource_id=plan_id,
            )

        try:
            imported_rows = await self._apply_plan_rows(db, plan_id, authority.id, ctx)
        except AdapterExecutionConflict:
            raise
        except Exception as exc:
            raise AdapterExecutionConflict(f"Plan '{plan_id}' execution failed: {exc}", resolved_resource_id=plan_id) from exc
        return imported_rows

    async def _apply_plan_rows(
        self, db: AsyncSession, plan_id: uuid.UUID, migration_authority_id: uuid.UUID, ctx
    ) -> int:
        """§8/§9/§23/§24 of the task. Reads the persisted plan rows in one
        deterministic order, bulk-prefetches every already-persisted
        event under this authority in one query (never a per-row
        `SELECT`), then inserts new events/refs in bounded batches.

        **Idempotency strategy (documented, not left implicit).** The
        primary mechanism is this function's own bulk prefetch: within
        one `execute()` attempt's single database transaction, the
        prefetched identity map is a stable snapshot, so every row in
        this loop is resolved against it deterministically, with zero
        risk of a race *within* this attempt (only one `execute()` can
        ever be in flight for one `ImportSession` at a time, per the
        framework's own single-winner admission). The remaining risk
        this defends against is a genuinely different, concurrently
        committing transaction (e.g. a second `ImportSession` re-
        importing the identical, already-executed workbook) inserting a
        colliding identity between this function's prefetch and its own
        insert. Rather than a fragile per-row `SAVEPOINT`-recover scheme,
        an unexpected `IntegrityError` on the bulk insert flush is
        treated the same as every other conflict in this framework: it
        fails the WHOLE attempt closed (§7 of the task's "any conflict
        rolls back the entire attempt" contract already established by
        `EquipmentMasterAdapter.execute()`) -- a retried dry-run/execute
        will then correctly observe the now-committed row via a fresh
        prefetch and skip it. This never overwrites an existing row and
        never silently reports success for one it could not verify."""
        rows = await legacy_history_dry_run_plan_crud.list_all_plan_rows(db, plan_id=plan_id)

        # §25 of the task: a defensive count check, derived from the same
        # adapter-owned admission policy PR21D1 already validated the
        # plan against -- never a new, duplicated magic number. The
        # persisted plan should already be within this bound; a plan that
        # somehow exceeds it indicates a framework-invariant violation.
        if len(rows) > common.PR21_MAX_IMPORT_RECORDS:
            raise AdapterExecutionConflict(
                f"Plan '{plan_id}' has {len(rows)} rows, exceeding the PR21 bounded admission allowance -- "
                "a framework-invariant violation.",
                resolved_resource_id=plan_id,
            )

        existing_by_identity = await legacy_equipment_event_crud.bulk_get_existing_by_identity(
            db, migration_authority_id=migration_authority_id
        )

        pending_events: list[LegacyEquipmentEvent] = []
        pending_refs: list[LegacyEquipmentEventSourceRef] = []
        imported_rows = 0

        for row in rows:
            identity_key = (row.event_type, row.legacy_source_row_key)
            normalized_values = row.normalized_values or {}
            existing = existing_by_identity.get(identity_key)
            if existing is not None:
                if not _plan_row_matches_existing_event(existing, normalized_values):
                    raise _LegacyEventIdentityConflictError(
                        event_type=row.event_type, legacy_source_row_key=row.legacy_source_row_key
                    )
                if not await self._existing_event_provenance_matches_plan(db, existing.id, normalized_values):
                    raise _LegacyEventIdentityConflictError(
                        event_type=row.event_type, legacy_source_row_key=row.legacy_source_row_key
                    )
                # §9 of the task: a proven-equivalent identity collision is
                # a safe, idempotent replay -- already fully applied by a
                # prior execution, so this row contributes nothing new.
                continue

            event_id = uuid.uuid4()
            try:
                equipment_id = uuid.UUID(normalized_values["equipment_id"])
                occurred_at = datetime.fromisoformat(normalized_values["occurred_at"])
            except (KeyError, ValueError) as exc:
                raise AdapterExecutionConflict(
                    f"Plan row for event_type={row.event_type!r}, "
                    f"legacy_source_row_key={row.legacy_source_row_key!r} carries a malformed normalized "
                    "equipment_id/occurred_at value.",
                    resolved_resource_id=plan_id,
                ) from exc
            resolved_ward_id_raw = normalized_values.get("resolved_ward_id")

            pending_events.append(
                LegacyEquipmentEvent(
                    id=event_id,
                    migration_authority_id=migration_authority_id,
                    equipment_id=equipment_id,
                    event_type=row.event_type,
                    occurred_at=occurred_at,
                    legacy_source_row_key=row.legacy_source_row_key,
                    legacy_order_reference=normalized_values.get("legacy_order_reference"),
                    legacy_ward_text=normalized_values.get("legacy_ward_text"),
                    resolved_ward_id=uuid.UUID(resolved_ward_id_raw) if resolved_ward_id_raw else None,
                    legacy_bme_name=normalized_values.get("legacy_bme_name"),
                    import_session_id=ctx.import_session_id,
                    import_source_id=ctx.import_source_id,
                )
            )
            # §11/§12 of the task: one ref per approved source coordinate
            # (header, line) -- the SAME physical header row legitimately
            # supports many different events (its own ref uniqueness is
            # scoped per-event, never globally), so no special-casing is
            # needed here to allow that.
            for ref_key in ("header_source_ref", "line_source_ref"):
                ref = normalized_values.get(ref_key)
                if not ref:
                    continue
                pending_refs.append(
                    LegacyEquipmentEventSourceRef(
                        legacy_equipment_event_id=event_id,
                        import_session_id=ctx.import_session_id,
                        import_source_id=ctx.import_source_id,
                        source_checksum=ctx.source_checksum,
                        sheet_name=ref["sheet_name"],
                        source_row_number=ref["source_row_number"],
                    )
                )
            imported_rows += 1

            if len(pending_events) >= _EXECUTE_BATCH_SIZE:
                await self._flush_batch(db, pending_events, pending_refs, plan_id)
                pending_events = []
                pending_refs = []

        await self._flush_batch(db, pending_events, pending_refs, plan_id)
        return imported_rows

    @staticmethod
    async def _flush_batch(
        db: AsyncSession,
        events: list[LegacyEquipmentEvent],
        refs: list[LegacyEquipmentEventSourceRef],
        plan_id: uuid.UUID,
    ) -> None:
        if not events and not refs:
            return
        try:
            await legacy_equipment_event_crud.bulk_insert_events(db, events)
            await legacy_equipment_event_crud.bulk_insert_source_refs(db, refs)
        except IntegrityError as exc:
            # See `_apply_plan_rows`'s own docstring: an unexpected
            # constraint violation here means a genuinely concurrent,
            # externally-committing transaction inserted a colliding
            # identity after this attempt's own prefetch -- fails the
            # whole attempt closed, exactly like every other conflict in
            # this framework, never a silent partial success.
            raise AdapterExecutionConflict(
                f"Plan '{plan_id}' execution hit an unexpected database identity conflict while inserting "
                "historical events -- a concurrent import likely committed the same identity first.",
                resolved_resource_id=plan_id,
            ) from exc

    async def _existing_event_provenance_matches_plan(
        self, db: AsyncSession, existing_event_id: uuid.UUID, normalized_values: dict
    ) -> bool:
        """§10 of the task's final equivalence bullet ("permanent
        provenance identity required by the plan"). Permissive by
        design: the existing event's own persisted refs must be a
        superset of what this plan row expects, not an exact set match
        -- a genuinely identical replay always satisfies this, while
        never being needlessly stricter than the task's own "same fact
        => safe replay" framing requires."""
        existing_refs = await legacy_equipment_event_crud.get_source_refs_for_event(
            db, legacy_equipment_event_id=existing_event_id
        )
        existing_coords = {(r.sheet_name, r.source_row_number) for r in existing_refs}
        expected_coords = set()
        for ref_key in ("header_source_ref", "line_source_ref"):
            ref = normalized_values.get(ref_key)
            if ref:
                expected_coords.add((ref["sheet_name"], ref["source_row_number"]))
        return expected_coords.issubset(existing_coords)

    async def on_execution_success(self, db: AsyncSession, resolved_resource_id: uuid.UUID | None) -> None:
        """Roadmap PR21D2 (mirrors `EquipmentMasterAdapter.
        on_execution_success` exactly). Called by the framework on TX1's
        own session, only after the Job->Session completion fence has
        already succeeded -- the plan is only ever marked `consumed`
        after that fence, never inside `execute()` itself, preserving the
        framework's global Job->Session->Plan lock order."""
        if resolved_resource_id is None:
            return
        await legacy_history_dry_run_plan_crud.mark_plan_consumed(db, plan_id=resolved_resource_id)

    async def on_execution_failure(self, db: AsyncSession, resolved_resource_id: uuid.UUID | None) -> None:
        """Roadmap PR21D2 (mirrors `EquipmentMasterAdapter.
        on_execution_failure` exactly). Called by the framework inside
        TX2, only after `fenced_phase_failure` has already succeeded --
        the same Job->Session->Plan lock order `on_execution_success`
        above and recovery both use."""
        if resolved_resource_id is None:
            return
        await legacy_history_dry_run_plan_crud.mark_plan_failed(db, plan_id=resolved_resource_id)

    async def on_execution_recovery(self, db: AsyncSession, session_id: uuid.UUID) -> None:
        """Roadmap PR21D2 (mirrors `EquipmentMasterAdapter.
        on_execution_recovery` exactly). Called by `recover_session()`
        only when the recovered job's `job_type` was `'execute'` --
        reconciles a hard worker crash during `execute()` that never
        raised anything at all. Since `execute()` runs entirely inside
        one database transaction, a hard crash before that transaction's
        own commit leaves no partial `LegacyEquipmentEvent`/
        `LegacyEquipmentEventSourceRef` row behind at all -- this hook's
        only job is marking the now-orphaned plan `failed`, exactly like
        the Equipment Master precedent."""
        await legacy_history_dry_run_plan_crud.mark_active_plan_failed_for_session(db, import_session_id=session_id)


register_adapter(LegacyTransactionHistoryAdapter())
