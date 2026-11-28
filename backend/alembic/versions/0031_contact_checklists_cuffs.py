"""Ward contact name, accessory/Cryo-Cuff checklists and cuff tracking (Roadmap PR27/PR28)

Revision ID: 0031_contact_checklists_cuffs
Revises: 0030_non_blocking_dispatch
Create Date: 2026-11-25

Owner Governance 2026-11-25 (D4, D7, D10, D11; docs/DECISION_LOG.md). Purely
additive:

- `borrow_transactions`: `dispatch_contact_name` / `receipt_contact_name`
  VARCHAR(100) NULL (D7, optional free-text ward-side contact; never a patient
  name), `checklist_kind` VARCHAR(20) NULL ('standard' | 'cryo_cuff', snapshot
  taken at dispatch; NULL for historical rows), `dispatch_checks` /
  `receipt_checks` JSONB NULL (validated checklist; NULL = not recorded).
  Existing rows stay NULL; nothing is backfilled.
- `equipment_categories.checklist_kind` VARCHAR(20) NOT NULL DEFAULT
  'standard' (explicit master data deciding which checklist applies). The
  backfill marks categories whose name contains "cryo" (case-insensitive) as
  'cryo_cuff'; administrators edit it afterwards (PATCH /categories/{id}).
- `transaction_cuffs` (D11): one balance row per (dispatch transaction, cuff
  type) with `issued_count` > 0 and 0 <= `returned_count` <= `issued_count`
  enforced by CHECK constraints, ON DELETE RESTRICT.

**Fresh-install vs. historical-upgrade convergence**, following 0023-0030.
The models declare every column/constraint/table above, so `0001_initial`'s
`create_all()` gives a new install the same schema as the `IF NOT EXISTS`
statements below give a database that applied 0001-0030;
`_verify_schema_convergence()` fails closed if the two paths disagree.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0030); SQLite
tests build the schema from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_contact_checklists_cuffs"
down_revision: Union[str, None] = "0030_non_blocking_dispatch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TX_CHECK = "ck_borrow_transactions_checklist_kind"
_CAT_CHECK = "ck_equipment_categories_checklist_kind"


def _add_check_if_missing(table: str, name: str, expression: str) -> str:
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = '{name}' AND conrelid = '{table}'::regclass
        ) THEN
            ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression});
        END IF;
    END
    $$
    """


_UPGRADE = [
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS dispatch_contact_name VARCHAR(100)",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS receipt_contact_name VARCHAR(100)",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS checklist_kind VARCHAR(20)",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS dispatch_checks JSONB",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS receipt_checks JSONB",
    _add_check_if_missing(
        "borrow_transactions", _TX_CHECK, "checklist_kind IS NULL OR checklist_kind IN ('standard', 'cryo_cuff')"
    ),
    "ALTER TABLE equipment_categories ADD COLUMN IF NOT EXISTS checklist_kind VARCHAR(20) NOT NULL DEFAULT 'standard'",
    _add_check_if_missing("equipment_categories", _CAT_CHECK, "checklist_kind IN ('standard', 'cryo_cuff')"),
    # Default mapping; editable afterwards. Only ever moves 'standard' rows.
    "UPDATE equipment_categories SET checklist_kind = 'cryo_cuff' "
    "WHERE checklist_kind = 'standard' AND lower(name) LIKE '%cryo%'",
    """
    CREATE TABLE IF NOT EXISTS transaction_cuffs (
        id UUID NOT NULL,
        transaction_id UUID NOT NULL REFERENCES borrow_transactions (id) ON DELETE RESTRICT,
        cuff_type VARCHAR(20) NOT NULL,
        issued_count INTEGER NOT NULL,
        returned_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        PRIMARY KEY (id),
        CONSTRAINT uq_transaction_cuffs_tx_type UNIQUE (transaction_id, cuff_type),
        CONSTRAINT ck_transaction_cuffs_type CHECK (cuff_type IN ('back_hip_rib', 'knee', 'shoulder', 'ankle')),
        CONSTRAINT ck_transaction_cuffs_issued_positive CHECK (issued_count > 0),
        CONSTRAINT ck_transaction_cuffs_returned_range CHECK (returned_count >= 0 AND returned_count <= issued_count)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_transaction_cuffs_transaction_id ON transaction_cuffs (transaction_id)",
]

_DOWNGRADE = [
    "DROP TABLE IF EXISTS transaction_cuffs",
    f"ALTER TABLE equipment_categories DROP CONSTRAINT IF EXISTS {_CAT_CHECK}",
    "ALTER TABLE equipment_categories DROP COLUMN IF EXISTS checklist_kind",
    f"ALTER TABLE borrow_transactions DROP CONSTRAINT IF EXISTS {_TX_CHECK}",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS receipt_checks",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS dispatch_checks",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS checklist_kind",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS receipt_contact_name",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS dispatch_contact_name",
]

_TS = "timestamp with time zone"
# table -> column -> (data_type, char_max_length|None, is_nullable, default_contains|None)
_EXPECTED = {
    "borrow_transactions": {
        "dispatch_contact_name": ("character varying", 100, "YES", None),
        "receipt_contact_name": ("character varying", 100, "YES", None),
        "checklist_kind": ("character varying", 20, "YES", None),
        "dispatch_checks": ("jsonb", None, "YES", None),
        "receipt_checks": ("jsonb", None, "YES", None),
    },
    "equipment_categories": {
        "checklist_kind": ("character varying", 20, "NO", "standard"),
    },
    "transaction_cuffs": {
        "id": ("uuid", None, "NO", None),
        "transaction_id": ("uuid", None, "NO", None),
        "cuff_type": ("character varying", 20, "NO", None),
        "issued_count": ("integer", None, "NO", None),
        "returned_count": ("integer", None, "NO", "0"),
        "created_at": (_TS, None, "NO", "now()"),
        "updated_at": (_TS, None, "NO", "now()"),
    },
}

_COLUMN_SQL = sa.text(
    """
    SELECT column_name, data_type, character_maximum_length, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = :table
    """
)

_EXPECTED_CHECKS = {
    "borrow_transactions": {_TX_CHECK},
    "equipment_categories": {_CAT_CHECK},
    "transaction_cuffs": {
        "ck_transaction_cuffs_type",
        "ck_transaction_cuffs_issued_positive",
        "ck_transaction_cuffs_returned_range",
    },
}


def _verify_schema_convergence() -> None:
    """Fail closed if the historical-upgrade path produced a schema the
    fresh-install path would not have."""
    bind = op.get_bind()
    for table, expected in _EXPECTED.items():
        actual = {r[0]: r[1:] for r in bind.execute(_COLUMN_SQL, {"table": table}).fetchall()}
        for column, (exp_type, exp_len, exp_nullable, exp_default) in expected.items():
            if column not in actual:
                raise RuntimeError(f"{table}.{column} is missing after this migration.")
            data_type, length, nullable, default = actual[column]
            if data_type != exp_type or length != exp_len or nullable != exp_nullable:
                raise RuntimeError(
                    f"{table}.{column} is {(data_type, length, nullable)!r}, "
                    f"expected {(exp_type, exp_len, exp_nullable)!r}."
                )
            if exp_default is None:
                if default is not None:
                    raise RuntimeError(f"{table}.{column} has unexpected default {default!r}.")
            elif default is None or exp_default not in str(default):
                raise RuntimeError(f"{table}.{column} default is {default!r}, expected {exp_default!r}.")
        if table == "transaction_cuffs" and set(actual) != set(expected):
            raise RuntimeError(f"transaction_cuffs columns differ: {sorted(set(actual) ^ set(expected))}.")
        names = {
            r[0]
            for r in bind.execute(
                sa.text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND contype = 'c'"),
                {"t": f"public.{table}"},
            ).fetchall()
        }
        missing = _EXPECTED_CHECKS[table] - names
        if missing:
            raise RuntimeError(f"{table} is missing CHECK constraints {sorted(missing)}.")
    fk_rules = [
        r[0]
        for r in bind.execute(
            sa.text(
                "SELECT confdeltype::text FROM pg_constraint "
                "WHERE conrelid = 'public.transaction_cuffs'::regclass AND contype = 'f'"
            )
        ).fetchall()
    ]
    if fk_rules != ["r"]:
        raise RuntimeError(f"transaction_cuffs must have one ON DELETE RESTRICT foreign key, found {fk_rules!r}.")


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
