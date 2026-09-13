import enum
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import UUIDStr

# Roadmap PR18B (docs/design/PR18_PRINTING_EXPORT_PLAN.md §7, §14): stable
# report identities. Not derived from a filename or localized title (§14) --
# these three values are the only ones this route family ever accepts, and
# are exactly the three report families Roadmap PR17 already implemented.
# The str base lets this double as the `report_id` path-parameter type in
# app.api.v1.reports, so an unsupported value fails FastAPI/Pydantic's own
# enum validation (a standard 422) before any handler code runs -- "Typed
# validation/not-found behavior; no generic format fallback" (design §19).


class ReportIdentity(str, enum.Enum):
    RECEIVE_REPORT = "receive-report"
    ISSUE_REPORT = "issue-report"
    EQUIPMENT_VERIFY_CHECKLIST = "equipment-verify-checklist"


# Roadmap PR18B (design §7.2 "Values"): semantic value types preserved as
# real Python types, not pre-converted to display strings -- a future Excel
# adapter (PR18E) needs a real date/decimal cell type, not text (design §11).
ExportValue = str | int | float | bool | date | datetime | None

ExportValueType = Literal["string", "integer", "decimal", "date", "datetime", "boolean"]


def _semantic_type_matches(value_type: ExportValueType, value: ExportValue) -> bool:
    """Roadmap PR18B review 4837529462 (PR18B-H3): exact semantic-type
    match for one `ExportRow` value against its column's declared
    `value_type`. `None` always matches (design §7.2 "Values" -- every
    column is nullable). `bool` is deliberately excluded from
    integer/decimal (Python's `bool` is an `int` subclass) and `datetime`
    is excluded from `date` (a `datetime` is-a `date`, but a `date` column
    must not silently accept a `datetime`) -- both would otherwise let a
    builder regression cross the type boundary undetected."""
    if value is None:
        return True
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "decimal":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type == "datetime":
        return isinstance(value, datetime)
    if value_type == "date":
        return isinstance(value, date) and not isinstance(value, datetime)
    return False


class ExportColumn(BaseModel):
    """One output-neutral column definition (design §7.2). Deliberately
    carries no renderer-specific property (no CSS class, no PDF coordinate,
    no workbook cell style) -- those belong to the future PR18C/PR18D/PR18E
    adapters, not this shared foundation."""

    key: str
    label_th: str
    value_type: ExportValueType

    model_config = {"frozen": True}


class ExportRow(BaseModel):
    """One data row, keyed by `ExportColumn.key` (design §7.2 "Rows").
    A named, stable type (not a bare untyped dict passed around by
    convention) -- adapters index into `values` by the column keys the same
    `ExportDocument.columns` list already declares."""

    values: dict[str, ExportValue]


class ExportFilterSummary(BaseModel):
    """One applied-filter line for the human-readable filter summary
    (design §1/§9/§13), e.g. {"label_th": "ช่วงวันที่ทำการ", "value": "1 - 15 ก.ค. 2569"}."""

    label_th: str
    value: str


class ExportMetadata(BaseModel):
    """Document generation metadata (design §7.2, §13). This is document
    metadata only -- never persistent audit logging (design §13: "PR18 does
    not introduce a new persistent domain audit record without Owner
    approval")."""

    report_identity: ReportIdentity
    display_name_th: str
    template_version: str = Field(min_length=1)
    generated_at: datetime
    generated_by_display_name: str
    generated_by_user_id: UUIDStr
    timezone: str
    applied_filters: list[ExportFilterSummary]
    row_count: int = Field(ge=0)
    filename_stem: str = Field(min_length=1)

    @field_validator("generated_at")
    @classmethod
    def _generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        # Roadmap PR18B review 4837529462 (PR18B-H3): a naive `generated_at`
        # is ambiguous to every future PDF/Excel adapter -- fail closed here
        # instead of letting an unqualified timestamp reach one of them.
        if value.tzinfo is None:
            raise ValueError("ExportMetadata.generated_at must be timezone-aware")
        return value


class ExportDocument(BaseModel):
    """The internal, output-neutral document model (design §5/§7.2).

    Not a public API contract -- never returned directly by any route.
    `app.schemas.report_export.PrintDocumentOut` (below) is the versioned,
    API-facing DTO the browser-print adapter (PR18C) actually consumes;
    `to_print_document_out()` maps one to the other so a future internal
    model change never silently changes the public API contract."""

    metadata: ExportMetadata
    columns: list[ExportColumn]
    rows: list[ExportRow]

    @model_validator(mode="after")
    def _validate_schema_invariants(self) -> "ExportDocument":
        # Roadmap PR18B review 4837529462 (PR18B-H3): this model is the
        # shared foundation every future PR18C/PR18D/PR18E adapter builds
        # on, so it must protect its own invariants rather than trust every
        # report builder to construct it correctly -- a duplicate column key,
        # a row with a missing/unexpected key, a row value whose type
        # conflicts with its column's declared `value_type`, or a
        # `row_count` that disagrees with `len(rows)` all fail closed here,
        # at construction time, in every one of the three report builders,
        # instead of silently reaching an output adapter later.
        column_keys = [c.key for c in self.columns]
        if len(column_keys) != len(set(column_keys)):
            duplicates = sorted({k for k in column_keys if column_keys.count(k) > 1})
            raise ValueError(f"ExportDocument.columns contains duplicate column keys: {duplicates}")

        column_key_set = set(column_keys)
        value_types = {c.key: c.value_type for c in self.columns}
        for index, row in enumerate(self.rows):
            row_key_set = set(row.values.keys())
            if row_key_set != column_key_set:
                missing = sorted(column_key_set - row_key_set)
                unexpected = sorted(row_key_set - column_key_set)
                raise ValueError(
                    f"ExportDocument.rows[{index}] keys do not match declared columns "
                    f"(missing={missing}, unexpected={unexpected})"
                )
            for key, value in row.values.items():
                if not _semantic_type_matches(value_types[key], value):
                    raise ValueError(
                        f"ExportDocument.rows[{index}]['{key}'] value {value!r} does not match "
                        f"column '{key}' declared value_type '{value_types[key]}'"
                    )

        if self.metadata.row_count != len(self.rows):
            raise ValueError(
                f"ExportMetadata.row_count ({self.metadata.row_count}) does not match "
                f"len(rows) ({len(self.rows)})"
            )
        return self


# ---------------------------------------------------------------------------
# Public, versioned API DTO for GET /reports/{report_id}/print-data (design
# §5 "Print-data adapter", §7.2). Structurally mirrors ExportDocument today,
# but is a deliberately distinct set of classes -- design §7.2: "The internal
# model is not an API contract. The browser-print adapter exposes a separate
# PrintDocumentOut API DTO derived from it."
# ---------------------------------------------------------------------------


class PrintColumnOut(BaseModel):
    key: str
    label_th: str
    value_type: ExportValueType


class PrintRowOut(BaseModel):
    values: dict[str, ExportValue]


class PrintFilterSummaryOut(BaseModel):
    label_th: str
    value: str


class PrintMetadataOut(BaseModel):
    report_identity: ReportIdentity
    display_name_th: str
    template_version: str
    generated_at: datetime
    generated_by_display_name: str
    generated_by_user_id: UUIDStr
    timezone: str
    applied_filters: list[PrintFilterSummaryOut]
    row_count: int
    filename_stem: str


class PrintDocumentOut(BaseModel):
    metadata: PrintMetadataOut
    columns: list[PrintColumnOut]
    rows: list[PrintRowOut]


def to_print_document_out(document: ExportDocument) -> PrintDocumentOut:
    """Maps the internal `ExportDocument` to the versioned `PrintDocumentOut`
    API contract (design §7.2). A one-to-one field mapping today -- kept as
    an explicit function (not `PrintDocumentOut.model_validate(document)`)
    so a future divergence between the internal model and the public
    contract (e.g. the internal model gaining a field the API must not yet
    expose) has one obvious place to enforce that boundary."""
    return PrintDocumentOut(
        metadata=PrintMetadataOut(
            report_identity=document.metadata.report_identity,
            display_name_th=document.metadata.display_name_th,
            template_version=document.metadata.template_version,
            generated_at=document.metadata.generated_at,
            generated_by_display_name=document.metadata.generated_by_display_name,
            generated_by_user_id=document.metadata.generated_by_user_id,
            timezone=document.metadata.timezone,
            applied_filters=[
                PrintFilterSummaryOut(label_th=f.label_th, value=f.value) for f in document.metadata.applied_filters
            ],
            row_count=document.metadata.row_count,
            filename_stem=document.metadata.filename_stem,
        ),
        columns=[PrintColumnOut(key=c.key, label_th=c.label_th, value_type=c.value_type) for c in document.columns],
        rows=[PrintRowOut(values=r.values) for r in document.rows],
    )
