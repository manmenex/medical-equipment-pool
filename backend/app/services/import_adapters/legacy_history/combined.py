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
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CREATED, AUDIT_ENTITY_IMPORT_SESSION, record_audit_event
from app.core.exceptions import InvalidInputError
from app.crud import legacy_history_dry_run_plan as legacy_history_dry_run_plan_crud
from app.crud import legacy_migration_authority as legacy_migration_authority_crud
from app.models.import_session import ImportSession
from app.models.legacy_history import LegacyHistoryDryRunPlanRow
from app.services.import_adapter import DryRunPlan, FieldError, ImportAdapter, RawImportRecord, register_adapter
from app.services.import_adapter_context import get_adapter_invocation_context
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

    # Deliberately NOT overridden -- `execute()`/`precheck_execute()`/
    # `on_execution_success`/`on_execution_failure`/`on_execution_recovery`
    # all keep `ImportAdapter`'s own defaults (§21/§55.5/§60/§61 of the
    # task): `execute()` raises `NotImplementedError`, so
    # `import_execution_service.run_execute`'s existing
    # `type(adapter).execute is ImportAdapter.execute` guard keeps
    # `POST .../execute` structurally unreachable for this dataset_type
    # until a future PR21D2 slice deliberately implements it.


register_adapter(LegacyTransactionHistoryAdapter())
