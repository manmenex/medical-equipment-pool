"""consolidate the 5-role legacy model into the confirmed 3-role model (Roadmap PR10)

Revision ID: 0009_role_consolidation
Revises: 0008_dispatch_fields
Create Date: 2026-07-23

Roadmap PR10 (docs/audits/03-hospital-equipment-pool-workflow-audit.md §10
"Role and Permission Review"; docs/audits/04-consolidated-implementation-plan.md
Part D's PR10 entry): replaces the legacy 5-role model (admin,
biomedical_engineer, ward_nurse, transport_staff, viewer) with the
confirmed 3-role business model (administrator, equipment_pool_staff,
read_only) everywhere a role is persisted.

This is explicitly NOT a mechanical migration
(docs/audits/04-consolidated-implementation-plan.md §14 item 5: "This is a
manual, per-person decision ... needs a named decision-owner before PR10
merges"). Exactly two legacy roles have a confirmed, evidence-backed
equivalent and are remapped automatically:

    admin  -> administrator
    viewer -> read_only

biomedical_engineer, ward_nurse, and transport_staff have NO confirmed
equivalent (the workflow audit's own §10 note: they "have no clear place in
this workflow as described") and are never auto-mapped. If any user
currently holds one of those three roles, this migration requires an
explicit, deployment-supplied mapping manifest -- a JSON array of
{"employee_code": ..., "target_role": ...} objects -- via the
MEP_PR10_ROLE_MAPPING environment variable, covering every such user by
their immutable employee_code. Validated before any role is rewritten:
every ambiguous-role user must have exactly one entry, every entry must
name an existing user and one of the 3 confirmed target roles, and no
employee_code may appear twice. If the manifest is missing, incomplete, or
invalid, upgrade() aborts with a RuntimeError listing the unresolved
employee_codes (never emails, password hashes, or any other sensitive
field) -- it never silently guesses, upgrades, or downgrades an ambiguous
account's privilege level. As of this revision, this repository's own
database (dev/CI seed and test fixtures) has zero users on any ambiguous
role, so upgrading here requires no manifest at all; the manifest mechanism
exists for a real deployment where such accounts might exist.

Provenance for lossless downgrade: every user's pre-migration role name is
captured into a new nullable `users.legacy_role_name` column before any
rewrite happens (mirrors BorrowTransaction.legacy_status's established
Roadmap PR7 pattern) -- this makes downgrade() fully lossless for every
user this migration actually touches, without needing the mapping manifest
supplied a second time. A user created *after* this migration's upgrade
(and therefore never given a legacy role) has no legacy_role_name to
restore; downgrade() aborts rather than fabricate one for such a user,
exactly like migration 0008's borrower_name downgrade guard.

Schema changes:
  - users.legacy_role_name  new, nullable VARCHAR(50); migration provenance
                             only, never read by the application, never
                             returned by any API response.
  - roles                   the 3 confirmed rows are inserted; the 5
                             legacy rows are deleted once no user
                             references them; a CHECK constraint then
                             restricts roles.name to exactly the 3
                             confirmed values (defense in depth -- the
                             application layer, via
                             app.models.user.ALL_ROLES and
                             app.schemas.master_data.RoleName, is still the
                             primary gate).

No equipment/transaction lifecycle, dispatch/receipt/ward-correction
contract, or unrelated schema change is part of this migration.

Audit: this migration never calls app.core.audit.record_audit_event or
writes to audit_logs -- it runs outside any authenticated HTTP request, so
there is no real actor to attribute a role change to, and fabricating one
(e.g. a synthetic "system" user_id) would misrepresent the audit trail.
Every user-facing role change made through the API (POST/PATCH
/api/v1/users) is still audited atomically with its role_id UPDATE, per
the existing PR3 audit framework -- unchanged by this migration.

Like migrations 0006/0007/0008, this migration does not import any
application module -- the confirmed role names and the legacy-to-new
mapping are defined locally, frozen at this revision, and duplicated
(deliberately) from app.models.user's own constants of the same name.
"""
import json
import os
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_role_consolidation"
down_revision: Union[str, None] = "0008_dispatch_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Revision-local, frozen value domains. See the immutability note in this
# module's docstring -- deliberately NOT imported from app.models.user.
# ---------------------------------------------------------------------------

NEW_ROLE_NAMES: tuple[str, ...] = ("administrator", "equipment_pool_staff", "read_only")
SAFE_LEGACY_ROLE_MAPPING: dict[str, str] = {"admin": "administrator", "viewer": "read_only"}
AMBIGUOUS_LEGACY_ROLES: tuple[str, ...] = ("biomedical_engineer", "ward_nurse", "transport_staff")
ALL_LEGACY_ROLES: tuple[str, ...] = (
    "admin",
    "biomedical_engineer",
    "ward_nurse",
    "transport_staff",
    "viewer",
)
MANIFEST_ENV_VAR = "MEP_PR10_ROLE_MAPPING"


def _load_manifest() -> dict[str, str]:
    """Parse and validate MEP_PR10_ROLE_MAPPING. Only ever called when at
    least one ambiguous-role user exists. Returns {employee_code:
    target_role}. Raises RuntimeError (never silently proceeds) on any
    structural problem -- missing, malformed JSON, wrong shape, duplicate
    employee_code, or an unrecognized target role."""
    raw = os.environ.get(MANIFEST_ENV_VAR)
    if not raw:
        raise RuntimeError(
            "Migration 0009 aborted: one or more users hold an ambiguous legacy role "
            f"({', '.join(AMBIGUOUS_LEGACY_ROLES)}) with no confirmed equivalent in the new "
            "3-role model. This is not a mechanical migration -- each such account requires a "
            "manual, reviewed decision. Set the MEP_PR10_ROLE_MAPPING environment variable to a "
            "JSON array of {employee_code, target_role} objects (target_role one of "
            "administrator, equipment_pool_staff, read_only) covering every such account, "
            "then retry. No role was changed."
        )
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Migration 0009 aborted: {MANIFEST_ENV_VAR} is not valid JSON ({exc}). No role was changed.") from exc

    if not isinstance(entries, list):
        raise RuntimeError(f"Migration 0009 aborted: {MANIFEST_ENV_VAR} must be a JSON array. No role was changed.")

    mapping: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "employee_code" not in entry or "target_role" not in entry:
            raise RuntimeError(
                f"Migration 0009 aborted: {MANIFEST_ENV_VAR} contains an entry that is not an object "
                'with "employee_code" and "target_role" keys. No role was changed.'
            )
        code = entry["employee_code"]
        target = entry["target_role"]
        if not isinstance(code, str) or not code:
            raise RuntimeError(f"Migration 0009 aborted: {MANIFEST_ENV_VAR} contains an invalid employee_code. No role was changed.")
        if code in mapping:
            raise RuntimeError(
                f"Migration 0009 aborted: {MANIFEST_ENV_VAR} names employee_code {code!r} more than once "
                "(duplicate mapping). No role was changed."
            )
        if target not in NEW_ROLE_NAMES:
            raise RuntimeError(
                f"Migration 0009 aborted: {MANIFEST_ENV_VAR} names an unknown target role {target!r} for "
                f"employee_code {code!r} -- must be one of {NEW_ROLE_NAMES}. No role was changed."
            )
        mapping[code] = target
    return mapping


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # SQLite test/dev databases build their schema via
        # Base.metadata.create_all() directly from the current ORM models
        # (see 0006/0007/0008's identical branch), which already reflect
        # only the 3 confirmed roles and the new legacy_role_name column.
        # There is no pre-PR10 data to remap in that path.
        return

    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS legacy_role_name VARCHAR(50)")

    # Step 1: capture every user's current role name before anything is
    # rewritten -- migration provenance, mirrors legacy_status (PR7).
    op.execute(
        "UPDATE users SET legacy_role_name = roles.name "
        "FROM roles WHERE users.role_id = roles.id AND users.legacy_role_name IS NULL"
    )

    # Step 2: validate the ambiguous-role mapping manifest BEFORE any role
    # is rewritten. Fails closed -- never guesses, never proceeds partially.
    ambiguous_rows = bind.execute(
        sa.text(
            "SELECT users.employee_code AS employee_code "
            "FROM users JOIN roles ON users.role_id = roles.id "
            "WHERE roles.name = ANY(:ambiguous)"
        ),
        {"ambiguous": list(AMBIGUOUS_LEGACY_ROLES)},
    ).mappings().all()

    manifest: dict[str, str] = {}
    if ambiguous_rows:
        manifest = _load_manifest()
        unresolved = sorted({row["employee_code"] for row in ambiguous_rows} - set(manifest))
        if unresolved:
            raise RuntimeError(
                "Migration 0009 aborted: MEP_PR10_ROLE_MAPPING does not cover every ambiguous-role "
                f"user. Unresolved employee_code(s): {unresolved}. No role was changed."
            )
        known_codes = {
            row[0] for row in bind.execute(sa.text("SELECT employee_code FROM users")).all()
        }
        unknown_refs = sorted(set(manifest) - known_codes)
        if unknown_refs:
            raise RuntimeError(
                "Migration 0009 aborted: MEP_PR10_ROLE_MAPPING references employee_code(s) that do "
                f"not exist: {unknown_refs}. No role was changed."
            )

    # Step 3: insert the 3 confirmed role rows if not already present.
    for name in NEW_ROLE_NAMES:
        exists = bind.execute(sa.text("SELECT 1 FROM roles WHERE name = :name"), {"name": name}).first()
        if not exists:
            bind.execute(
                sa.text("INSERT INTO roles (id, name, permissions) VALUES (:id, :name, '{}'::jsonb)"),
                {"id": str(uuid.uuid4()), "name": name},
            )

    # Step 4: safe automatic remaps (admin -> administrator, viewer -> read_only).
    for legacy_name, new_name in SAFE_LEGACY_ROLE_MAPPING.items():
        bind.execute(
            sa.text(
                "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = :new_name) "
                "WHERE role_id = (SELECT id FROM roles WHERE name = :legacy_name)"
            ),
            {"new_name": new_name, "legacy_name": legacy_name},
        )

    # Step 5: manifest-driven remaps for ambiguous-role users.
    for employee_code, target_role in manifest.items():
        bind.execute(
            sa.text(
                "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = :target_role) "
                "WHERE employee_code = :employee_code"
            ),
            {"target_role": target_role, "employee_code": employee_code},
        )

    # Step 6: verify (never assume) that no user still references a legacy
    # role before deleting those rows -- deleting first would either FK-fail
    # or, if unconstrained, silently orphan a user's role_id.
    remaining = bind.execute(
        sa.text(
            "SELECT count(*) FROM users JOIN roles ON users.role_id = roles.id WHERE roles.name = ANY(:legacy)"
        ),
        {"legacy": list(ALL_LEGACY_ROLES)},
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"Migration 0009 aborted: {remaining} user(s) still reference a legacy role after "
            "remapping -- this should be unreachable given the checks above; investigate before "
            "retrying. No legacy role row was deleted."
        )

    op.execute(
        "DELETE FROM roles WHERE name = ANY(ARRAY['admin','biomedical_engineer','ward_nurse','transport_staff','viewer'])"
    )

    # Defense in depth: the application layer (app.models.user.ALL_ROLES,
    # app.schemas.master_data.RoleName) is the primary gate; this CHECK
    # additionally makes it impossible for any future direct SQL write to
    # reintroduce a retired or unrecognized role name.
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT ck_roles_name_confirmed "
        "CHECK (name IN ('administrator', 'equipment_pool_staff', 'read_only'))"
    )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE roles DROP CONSTRAINT IF EXISTS ck_roles_name_confirmed")

    # A user with no recorded legacy_role_name was created after this
    # migration's upgrade and never held a legacy role -- there is nothing
    # true to restore it to. Fails closed rather than fabricate one,
    # exactly like migration 0008's borrower_name downgrade guard.
    missing = bind.execute(sa.text("SELECT count(*) FROM users WHERE legacy_role_name IS NULL")).scalar_one()
    if missing:
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: {missing} user(s) have no recorded legacy_role_name "
            "(created after this migration's upgrade) and cannot be losslessly restored to a pre-PR10 "
            "role. Back up and hand-resolve these rows before downgrading, or prefer a forward fix instead."
        )

    for name in ALL_LEGACY_ROLES:
        exists = bind.execute(sa.text("SELECT 1 FROM roles WHERE name = :name"), {"name": name}).first()
        if not exists:
            bind.execute(
                sa.text("INSERT INTO roles (id, name, permissions) VALUES (:id, :name, '{}'::jsonb)"),
                {"id": str(uuid.uuid4()), "name": name},
            )

    # Restore every user's role_id from their recorded legacy_role_name --
    # lossless for every user this migration's upgrade touched, since it
    # never needs the mapping manifest supplied a second time.
    op.execute("UPDATE users SET role_id = roles.id FROM roles WHERE roles.name = users.legacy_role_name")

    remaining = bind.execute(
        sa.text(
            "SELECT count(*) FROM users JOIN roles ON users.role_id = roles.id WHERE roles.name = ANY(:new_roles)"
        ),
        {"new_roles": list(NEW_ROLE_NAMES)},
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: {remaining} user(s) still reference a confirmed "
            "3-role-model role after restoring legacy roles -- this should be unreachable; investigate "
            "before retrying. No confirmed role row was deleted."
        )

    op.execute("DELETE FROM roles WHERE name = ANY(ARRAY['administrator','equipment_pool_staff','read_only'])")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS legacy_role_name")
