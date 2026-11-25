"""Daily-report ward -> report-row mapping (Roadmap PR30)

Revision ID: 0032_report_ward_rows
Revises: 0031_contact_checklists_cuffs
Create Date: 2026-11-25

Owner Governance 2026-11-25 (D5). Purely additive: one new table
`report_ward_rows` (optional per-ward override of the daily report row label,
treatment type, dispense mode and sort order). No rows are seeded; wards
without a row use their own name / department by default.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0031); SQLite
tests build the schema from ORM metadata. The model declares the same table,
so `0001_initial`'s `create_all()` gives a new install the same schema.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_report_ward_rows"
down_revision: Union[str, None] = "0031_contact_checklists_cuffs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = """
CREATE TABLE IF NOT EXISTS report_ward_rows (
    id UUID NOT NULL,
    ward_id UUID NOT NULL REFERENCES wards (id) ON DELETE RESTRICT,
    report_row_label VARCHAR(100),
    treatment_type VARCHAR(100),
    dispense_mode VARCHAR(100),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT uq_report_ward_rows_ward_id UNIQUE (ward_id)
)
"""

_EXPECTED_COLUMNS = {
    "id": ("uuid", None, "NO"),
    "ward_id": ("uuid", None, "NO"),
    "report_row_label": ("character varying", 100, "YES"),
    "treatment_type": ("character varying", 100, "YES"),
    "dispense_mode": ("character varying", 100, "YES"),
    "sort_order": ("integer", None, "NO"),
    "created_at": ("timestamp with time zone", None, "NO"),
    "updated_at": ("timestamp with time zone", None, "NO"),
}


def _verify_schema_convergence() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'report_ward_rows'"
        )
    ).fetchall()
    actual = {r[0]: tuple(r[1:]) for r in rows}
    if actual != _EXPECTED_COLUMNS:
        raise RuntimeError(f"report_ward_rows schema differs from the model: {actual!r}")
    fk_rules = [
        r[0]
        for r in bind.execute(
            sa.text(
                "SELECT confdeltype::text FROM pg_constraint "
                "WHERE conrelid = 'public.report_ward_rows'::regclass AND contype = 'f'"
            )
        ).fetchall()
    ]
    if fk_rules != ["r"]:
        raise RuntimeError(f"report_ward_rows must have one ON DELETE RESTRICT foreign key, found {fk_rules!r}.")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text(_UPGRADE))
    _verify_schema_convergence()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text("DROP TABLE IF EXISTS report_ward_rows"))
