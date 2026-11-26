"""Standby summary: overrides, config/baseline, hn_added_at (Roadmap PR34)

Revision ID: 0035_standby_summary
Revises: 0034_demo_loan_equipment
Create Date: 2026-11-26

Owner Governance 2026-11-26 (D15, D16; docs/DECISION_LOG.md). Purely additive:

- `borrow_transactions.hn_added_at` TIMESTAMPTZ NULL: set only when an HN is
  added after the dispatch (D15). Existing rows stay NULL.
- `standby_summary_overrides`: one staff-edited number per (summary date,
  cut-off, field key); unique on that triple.
- `standby_summary_config`: one row per role ('infusion' | 'pneumatic') with
  the optional explicit category and the charger/clamp baseline. No rows are
  seeded; the default category is a name match computed at read time.

NOTE (parallel work): Roadmap PR33 adds migration 0034 (demo/loan equipment).
This revision currently chains onto 0033; when PR33 merges first, change
`down_revision` below to PR33's 0034 revision id (no other change needed).

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0033); SQLite
tests build the schema from ORM metadata, and `0001_initial`'s `create_all()`
gives a fresh install the same schema (`_verify_schema_convergence()` fails
closed if the two paths disagree).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035_standby_summary"
down_revision: Union[str, None] = "0034_demo_loan_equipment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = [
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS hn_added_at TIMESTAMP WITH TIME ZONE",
    """
    CREATE TABLE IF NOT EXISTS standby_summary_overrides (
        id UUID NOT NULL,
        summary_date DATE NOT NULL,
        cutoff VARCHAR(5) NOT NULL,
        section VARCHAR(20) NOT NULL,
        field_key VARCHAR(120) NOT NULL,
        value INTEGER NOT NULL,
        edited_by_user_id UUID REFERENCES users (id) ON DELETE RESTRICT,
        edited_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        PRIMARY KEY (id),
        CONSTRAINT uq_standby_override_key UNIQUE (summary_date, cutoff, field_key),
        CONSTRAINT ck_standby_override_cutoff CHECK (cutoff IN ('night', 'day')),
        CONSTRAINT ck_standby_override_value CHECK (value >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS standby_summary_config (
        id UUID NOT NULL,
        category_role VARCHAR(20) NOT NULL,
        category_id UUID REFERENCES equipment_categories (id) ON DELETE RESTRICT,
        chargers INTEGER,
        clamps INTEGER,
        baseline_set_at TIMESTAMP WITH TIME ZONE,
        baseline_set_by_user_id UUID REFERENCES users (id) ON DELETE RESTRICT,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        PRIMARY KEY (id),
        CONSTRAINT uq_standby_config_role UNIQUE (category_role),
        CONSTRAINT ck_standby_config_role CHECK (category_role IN ('infusion', 'pneumatic')),
        CONSTRAINT ck_standby_config_chargers CHECK (chargers IS NULL OR chargers >= 0),
        CONSTRAINT ck_standby_config_clamps CHECK (clamps IS NULL OR clamps >= 0)
    )
    """,
]

_DOWNGRADE = [
    "DROP TABLE IF EXISTS standby_summary_config",
    "DROP TABLE IF EXISTS standby_summary_overrides",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS hn_added_at",
]

_TS = "timestamp with time zone"
# table -> column -> (data_type, char_max_length|None, is_nullable)
_EXPECTED = {
    "borrow_transactions": {"hn_added_at": (_TS, None, "YES")},
    "standby_summary_overrides": {
        "id": ("uuid", None, "NO"),
        "summary_date": ("date", None, "NO"),
        "cutoff": ("character varying", 5, "NO"),
        "section": ("character varying", 20, "NO"),
        "field_key": ("character varying", 120, "NO"),
        "value": ("integer", None, "NO"),
        "edited_by_user_id": ("uuid", None, "YES"),
        "edited_at": (_TS, None, "NO"),
        "created_at": (_TS, None, "NO"),
        "updated_at": (_TS, None, "NO"),
    },
    "standby_summary_config": {
        "id": ("uuid", None, "NO"),
        "category_role": ("character varying", 20, "NO"),
        "category_id": ("uuid", None, "YES"),
        "chargers": ("integer", None, "YES"),
        "clamps": ("integer", None, "YES"),
        "baseline_set_at": (_TS, None, "YES"),
        "baseline_set_by_user_id": ("uuid", None, "YES"),
        "created_at": (_TS, None, "NO"),
        "updated_at": (_TS, None, "NO"),
    },
}
_NEW_TABLES = ("standby_summary_overrides", "standby_summary_config")
_EXPECTED_FKS = {"standby_summary_overrides": 1, "standby_summary_config": 2}


def _verify_schema_convergence() -> None:
    bind = op.get_bind()
    for table, expected in _EXPECTED.items():
        rows = bind.execute(
            sa.text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t"
            ),
            {"t": table},
        ).fetchall()
        actual = {r[0]: tuple(r[1:]) for r in rows}
        for column, spec in expected.items():
            if actual.get(column) != spec:
                raise RuntimeError(f"{table}.{column} is {actual.get(column)!r}, expected {spec!r}.")
        if table in _NEW_TABLES and set(actual) != set(expected):
            raise RuntimeError(f"{table} columns differ: {sorted(set(actual) ^ set(expected))}.")
    for table, count in _EXPECTED_FKS.items():
        rules = [
            r[0]
            for r in bind.execute(
                sa.text(
                    "SELECT confdeltype::text FROM pg_constraint "
                    "WHERE conrelid = CAST(:t AS regclass) AND contype = 'f'"
                ),
                {"t": f"public.{table}"},
            ).fetchall()
        ]
        if rules != ["r"] * count:
            raise RuntimeError(f"{table} must have {count} ON DELETE RESTRICT foreign keys, found {rules!r}.")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in _UPGRADE:
        op.execute(sa.text(statement))
    _verify_schema_convergence()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in _DOWNGRADE:
        op.execute(sa.text(statement))
