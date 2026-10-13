"""Login lockout: 5 consecutive failures locks an account for 10 minutes

Revision ID: 0024_login_lockout
Revises: 0023_user_must_change_password
Create Date: 2026-10-13

Adds two purely additive columns, `users.failed_login_attempts` and
`users.locked_until`. No table is created, no column is dropped, no existing
value is rewritten.

**Why PostgreSQL and not Redis.** Redis is optional in this deployment --
`GET /api/v1/ready` reports `redis: degraded` and the application keeps
serving requests -- so a lockout counter living only in the cache would
silently stop existing whenever Redis was down, with nothing in the
application reporting that the control had gone. A security control that
vanishes without a trace is worse than no control, because its absence is
invisible. These columns are on the row the login path already reads.

**Why existing rows start unlocked.** `failed_login_attempts` defaults to 0
and `locked_until` to NULL, so every account that exists when this migration
runs is explicitly not locked. The alternative -- a NOT NULL `locked_until`
with some sentinel -- would make "never locked" and "lock expired" different
states for no benefit, and a nullable column says exactly what is meant.

**Fresh-install vs. historical-upgrade convergence**, following the
discipline migrations 0015-0023 established. `app.models.user` declares both
columns with matching `server_default`s, so `0001_initial.py`'s
`Base.metadata.create_all()` gives a brand-new install the same physical
columns -- type, nullability, and catalog default -- as the `ADD COLUMN`
statements below give a database that historically applied 0001-0023.
`_verify_schema_convergence()` asserts the two paths agree and fails closed
if they do not. Migration 0023 earned that check its keep on its first real
run: a column declared with SQLAlchemy's Python-side `default=` only produced
no catalog default on the fresh-install path, and `ADD COLUMN IF NOT EXISTS`
then found the column already present and did nothing, so the divergence
could be detected but never repaired by re-running. Both columns here carry
`server_default` for that reason.

Only ever runs raw SQL against PostgreSQL (see 0002/0004/0011-0023's
identical dialect-gated pattern) -- SQLite tests create these columns via
`Base.metadata.create_all()` directly (`tests/conftest.py`), never via this
migration chain, so ORM model correctness alone is authoritative there.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_login_lockout"
down_revision: Union[str, None] = "0023_user_must_change_password"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ADD_COLUMNS = """
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP WITH TIME ZONE
"""

_DROP_COLUMNS = """
ALTER TABLE users
    DROP COLUMN IF EXISTS failed_login_attempts,
    DROP COLUMN IF EXISTS locked_until
"""

# Captured empirically from a real PostgreSQL 16 catalog after creating these
# columns both ways (this migration, and Base.metadata.create_all()), never
# hand-guessed. Shape: (data_type, is_nullable, column_default_contains).
# `column_default_contains` is None where no catalog default is expected.
_EXPECTED_COLUMNS = {
    "failed_login_attempts": ("integer", "NO", "0"),
    "locked_until": ("timestamp with time zone", "YES", None),
}

_COLUMN_SQL = sa.text(
    """
    SELECT data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'users'
      AND column_name = :column
    """
)


def _verify_schema_convergence() -> None:
    """Fail closed if the historical-upgrade path produced columns the
    fresh-install path would not have."""
    bind = op.get_bind()
    for column, (expected_type, expected_nullable, expected_default) in (
        _EXPECTED_COLUMNS.items()
    ):
        row = bind.execute(_COLUMN_SQL, {"column": column}).fetchone()
        if row is None:
            raise RuntimeError(
                f"users.{column} is missing after this migration's own ADD COLUMN ran -- "
                "this indicates an internal migration bug, not a pre-existing "
                "incompatible schema."
            )
        data_type, is_nullable, column_default = row
        if data_type != expected_type:
            raise RuntimeError(
                f"users.{column} has data_type {data_type!r}, expected {expected_type!r}."
            )
        if is_nullable != expected_nullable:
            raise RuntimeError(
                f"users.{column} is_nullable is {is_nullable!r}, expected "
                f"{expected_nullable!r}."
            )
        if expected_default is None:
            if column_default is not None:
                raise RuntimeError(
                    f"users.{column} has catalog default {column_default!r}, expected none. "
                    "A default on locked_until would make every account look locked, or "
                    "permanently unlockable, depending on the value."
                )
        elif column_default is None or expected_default not in str(column_default):
            raise RuntimeError(
                f"users.{column} default is {column_default!r}, expected it to contain "
                f"{expected_default!r}. Without it, an account created by the "
                "fresh-install path would have a NULL attempt counter and every login "
                "would fail on the arithmetic."
            )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text(_ADD_COLUMNS))
    _verify_schema_convergence()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text(_DROP_COLUMNS))
