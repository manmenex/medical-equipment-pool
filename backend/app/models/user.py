import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.mixins import TimestampMixin, UTCDateTime, UUIDPKMixin

JSONType = JSONB().with_variant(JSON(), "sqlite")

# Roadmap PR10 (Role Model Consolidation, docs/audits/03-hospital-equipment
# -pool-workflow-audit.md §10): the confirmed 3-role business model. This is
# the single canonical definition of a valid, assignable role name -- every
# other module (schemas, deps, seed, tests) imports these constants rather
# than repeating string literals, so there is exactly one place to change if
# the confirmed matrix is ever revisited.
ROLE_ADMINISTRATOR = "administrator"
ROLE_EQUIPMENT_POOL_STAFF = "equipment_pool_staff"
ROLE_READ_ONLY = "read_only"

ALL_ROLES = [ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY]

# Retired by Roadmap PR10's migration (0009_role_consolidation.py). These
# names must never be used for a new role assignment, a `require_roles(...)`
# check, or a seed/test user after that migration runs -- the migration
# deletes the corresponding `roles` rows entirely, so `get_role_by_name`
# will no longer resolve any of them. Kept here, named, only because the
# migration itself and historical test fixtures need to refer to the exact
# pre-PR10 values by name.
LEGACY_ROLE_ADMIN = "admin"
LEGACY_ROLE_BIOMEDICAL_ENGINEER = "biomedical_engineer"
LEGACY_ROLE_WARD_NURSE = "ward_nurse"
LEGACY_ROLE_TRANSPORT_STAFF = "transport_staff"
LEGACY_ROLE_VIEWER = "viewer"

ALL_LEGACY_ROLES = [
    LEGACY_ROLE_ADMIN,
    LEGACY_ROLE_BIOMEDICAL_ENGINEER,
    LEGACY_ROLE_WARD_NURSE,
    LEGACY_ROLE_TRANSPORT_STAFF,
    LEGACY_ROLE_VIEWER,
]

# Roadmap PR10 migration decision (docs/DECISION_LOG.md "Roadmap PR10"): the
# only two legacy roles with a confirmed, evidence-backed equivalent in the
# new 3-role model. biomedical_engineer/ward_nurse/transport_staff have no
# confirmed equivalent (docs/audits/03-hospital-equipment-pool-workflow-audit.md
# §10's own note) and must never be auto-mapped -- see
# backend/alembic/versions/0009_role_consolidation.py.
SAFE_LEGACY_ROLE_MAPPING = {
    LEGACY_ROLE_ADMIN: ROLE_ADMINISTRATOR,
    LEGACY_ROLE_VIEWER: ROLE_READ_ONLY,
}


class Role(UUIDPKMixin, Base):
    __tablename__ = "roles"
    # Roadmap PR15B (docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §6.4): explicit
    # name converges with migration 0014's `uq_roles_name` rename instead of
    # leaving `unique=True` produce PostgreSQL's unnamed `roles_name_key`.
    __table_args__ = (UniqueConstraint("name", name="uq_roles_name"),)

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    permissions: Mapped[dict] = mapped_column(JSONType, default=dict)

    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("employee_code", name="uq_users_employee_code"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    employee_code: Mapped[str] = mapped_column(String(30), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Roadmap PR10 migration provenance (mirrors BorrowTransaction.
    # legacy_status's established pattern, Roadmap PR7): the exact legacy
    # role name (see ALL_LEGACY_ROLES) this user held immediately before
    # migration 0009_role_consolidation.py reassigned role_id to one of the
    # 3 new roles. Never fabricated, never backfilled for a user created
    # after that migration -- NULL for any such user. Read-only history;
    # no endpoint accepts or returns it as a live business value, and it is
    # never used for authorization. Exists solely so the migration's own
    # downgrade() can losslessly restore every user's pre-PR10 role,
    # including one migrated via 0009's manual ambiguous-role mapping.
    legacy_role_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    role: Mapped["Role"] = relationship(back_populates="users")
