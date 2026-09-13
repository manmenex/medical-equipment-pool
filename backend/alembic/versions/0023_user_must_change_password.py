"""Self-service password change + forced change on first login

Revision ID: 0023_user_must_change_password
Revises: 0022_cutover_go_no_go_decision
Create Date: 2026-09-13

Adds one purely additive column, `users.must_change_password`. No table is
created, no column is dropped, no existing value is rewritten.

**Why False for existing rows.** The flag means "this password was set by
somebody other than the account's owner". Every row that exists when this
migration runs has a password chosen under the previous rules; defaulting
them to True would lock every current user out of the application on deploy
until they reset, which is a change nobody asked for and which the local
Staging/UAT operator would experience as an outage. New accounts and
Administrator-set passwords get True from the application layer
(app/scripts/bootstrap_admin.py and the users PATCH endpoint), not from here.

**Fresh-install vs. historical-upgrade convergence**, following the
discipline migrations 0015-0022 established. `app.models.user` already
declares the column, so `0001_initial.py`'s `Base.metadata.create_all()`
gives a brand-new install the column with the same type, nullability and
default. This migration's raw SQL is what adds it to a database that
historically applied 0001-0022 before this slice existed.
`_verify_schema_convergence()` below asserts the two paths agree, and fails
closed if they do not.

Only ever runs raw SQL against PostgreSQL (see 0002/0004/0011-0022's
identical dialect-gated pattern) -- SQLite tests create this column via
`Base.metadata.create_all()` directly (`tests/conftest.py`), never via this
migration chain, so ORM model correctness alone is authoritative there.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_user_must_change_password"
down_revision: Union[str, None] = "0022_cutover_go_no_go_decision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ADD_COLUMN = """
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE
"""

_DROP_COLUMN = """
ALTER TABLE users
    DROP COLUMN IF EXISTS must_change_password
"""

# Captured empirically from a real PostgreSQL 16 catalog after creating the
# column both ways (this migration, and Base.metadata.create_all()), never
# hand-guessed.
_EXPECTED_DATA_TYPE = "boolean"
_EXPECTED_IS_NULLABLE = "NO"
_EXPECTED_DEFAULT = "false"


def _verify_schema_convergence() -> None:
    """Fail closed if the historical-upgrade path produced a column the
    fresh-install path would not have."""
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            """
            SELECT data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'must_change_password'
            """
        )
    ).fetchone()
    if row is None:
        raise RuntimeError(
            "users.must_change_password is missing after this migration ran -- refusing to continue."
        )
    data_type, is_nullable, column_default = row
    if data_type != _EXPECTED_DATA_TYPE:
        raise RuntimeError(
            f"users.must_change_password has data_type {data_type!r}, expected {_EXPECTED_DATA_TYPE!r}."
        )
    if is_nullable != _EXPECTED_IS_NULLABLE:
        raise RuntimeError(
            f"users.must_change_password is_nullable is {is_nullable!r}, expected {_EXPECTED_IS_NULLABLE!r}. "
            "A nullable flag would make 'unknown' indistinguishable from 'not required'."
        )
    if column_default is None or _EXPECTED_DEFAULT not in str(column_default).lower():
        raise RuntimeError(
            f"users.must_change_password default is {column_default!r}, expected it to contain "
            f"{_EXPECTED_DEFAULT!r}. Existing accounts must not be locked out by this deploy."
        )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text(_ADD_COLUMN))
    _verify_schema_convergence()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text(_DROP_COLUMN))
