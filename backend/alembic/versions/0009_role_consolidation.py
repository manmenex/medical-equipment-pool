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
name an existing user whose *current* role is genuinely ambiguous (never
admin/viewer/an already-confirmed role -- the manifest can only ever
narrow an ambiguous account, never override the safe automatic mapping or
a role that isn't ambiguous in the first place), and every entry's target
must be one of the 3 confirmed roles, with no employee_code appearing
twice. If the manifest is missing, incomplete, or invalid in any of these
ways, upgrade() aborts with a RuntimeError listing the unresolved/rejected
employee_codes (never emails, password hashes, or any other sensitive
field) -- it never silently guesses, upgrades, or downgrades an ambiguous
account's privilege level, and no audit/provenance row is written for a
run that aborts. As of this revision, this repository's own database
(dev/CI seed and test fixtures) has zero users on any ambiguous role, so
upgrading here requires no manifest at all; the manifest mechanism exists
for a real deployment where such accounts might exist.

Schema inspection note (Codex review round 2 on PR #36, finding H3): this
codebase has no normalized role-permission table -- `roles` has exactly
two content columns, `name` and a single `permissions` JSONB blob column
(`backend/app/models/user.py`'s `Role` model), always `{}` as of this
revision. There is no separate "permission" entity with its own stable ID
to preserve a relationship against. `roles.id` is a UUID (`UUIDPKMixin`),
not an integer with a sequence. Every snapshot and restoration below is
sized to this actual schema, not a hypothetical one: capturing a legacy
role's exact `(id, name, permissions)` tuple *is* capturing its complete
metadata and its complete "permission relationship" simultaneously, since
in this schema the permission relationship has no existence independent of
that JSONB column. No sequence-adjustment step is needed or included,
since UUIDs never collide with a sequence's next value.

Provenance and lossless, safe upgrade/downgrade: every actual role change
this migration performs -- in either direction -- is recorded atomically
with the role_id UPDATE itself (same transaction; a failure writing any
provenance record aborts that user's role change too, and prevents every
other pending change in that run from being committed):

  1. `role_migration_snapshots` -- an exact, row-for-row capture of every
     legacy role that exists in `roles` at the moment upgrade() runs
     (whatever subset of the 5 legacy names actually has a row -- never
     assumed to be all 5), taken BEFORE the new 3-role model is created or
     any legacy role is touched. Captures the legacy role's exact `id`,
     `name`, and `permissions` -- not just its name -- so downgrade() can
     recreate the *exact original row*, never a same-named row with a
     freshly generated id. UNIQUE(revision, legacy_role_id) makes a
     duplicate/inconsistent snapshot for the same role structurally
     impossible, not just checked at runtime.
  2. `user_role_migrations` -- one row per user this migration actually
     changes, recording both the exact legacy role id/name the user held
     and the exact migrated role id/name they were moved to
     (UNIQUE(user_id, revision)). This is downgrade()'s sole source of
     truth for "is it still safe to restore this user," compared by exact
     role id, never by name and never inferred from the new role alone --
     multiple ambiguous legacy roles can map to the same new role, so
     reverse inference would be invalid. A legitimate post-upgrade role
     change (made through the ordinary POST/PATCH /api/v1/users API) is
     therefore never silently overwritten: downgrade() aborts, atomically
     and before any write, the moment any migrated user's current role id
     no longer matches what this table recorded, or any user currently
     holding a confirmed role has no recorded metadata for this revision
     at all (created after the upgrade, so there is nothing true to
     restore).
  3. `audit_logs` -- one row per changed user, in whichever direction the
     change happened: `action="role_migration_upgrade"` when upgrade()
     changes a role, `action="role_migration_downgrade"` when downgrade()
     restores one -- deliberately distinct action strings so the two
     directions are never ambiguous in a query or a read of the table.
     Both reuse the table's existing nullable `user_id` column (already
     used elsewhere for a system/non-human event, e.g. a login failure
     against an unknown identifier) to record a truthful system/migration
     actor -- never a fabricated authenticated user.

The pre-existing `users.legacy_role_name` column (added by this same
migration, mirroring `BorrowTransaction.legacy_status`'s Roadmap PR7
pattern) is still populated for every user before any rewrite, as a
simple, single-column, human-readable record of "what role did this user
have going into Roadmap PR10" -- but it is provenance-only, never read by
the application, and (unlike `user_role_migrations`/
`role_migration_snapshots`) is not downgrade()'s authority, since a role
name alone cannot losslessly reconstruct the original row identity or
distinguish "still safe to restore" from "diverged after upgrade."

Schema changes:
  - users.legacy_role_name    new, nullable VARCHAR(50); migration
                                provenance only, never read by the
                                application, never returned by any API
                                response.
  - user_role_migrations      new table; downgrade()'s per-user authority
                                (see point 2 above). Created and fully
                                dropped by this revision's upgrade/
                                downgrade respectively -- no other
                                revision or application code reads it.
  - role_migration_snapshots  new table; downgrade()'s per-role-row
                                authority (see point 1 above). Created and
                                fully dropped by this revision's upgrade/
                                downgrade respectively.
  - audit_logs                gains one row per user this migration
                                changes, in either direction (no column
                                change -- the table's existing nullable
                                `user_id` and JSONB before_data/after_data
                                columns are sufficient).
  - roles                     the 3 confirmed rows are inserted; the
                                legacy rows actually present are deleted
                                once no user references them; a CHECK
                                constraint then restricts roles.name to
                                exactly the 3 confirmed values (defense in
                                depth -- the application layer, via
                                app.models.user.ALL_ROLES and
                                app.schemas.master_data.RoleName, is still
                                the primary gate).

No equipment/transaction lifecycle, dispatch/receipt/ward-correction
contract, or unrelated schema change is part of this migration.

Design note (Codex review round 2, migration design constraints): PR10 is
unmerged, so this fix is made directly in this revision file rather than
stacked as a follow-up migration -- there is no already-deployed copy of
0009 anywhere for a stacked fix to be safer against, and stacking one here
would only add an avoidable extra revision to review. The upgrade step
order below adapts the reviewed suggestion in one place: capturing a
user's `migrated_role_id` genuinely requires the new role rows to already
exist (their ids are generated at insert time), so the per-user
`user_role_migrations` row is written in the same per-user step that
performs the role_id UPDATE (as it already was before this fix round),
immediately after the role-level `role_migration_snapshots` capture and
the confirmed-role-model creation that necessarily precedes it -- not
before them. The *role*-level snapshot (point 1 above), which has no such
dependency, is still taken first, before any roles-table mutation.

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

# Migration-provenance audit constants (see module docstring, point 3).
# Deliberately distinct action strings per direction -- never ambiguous.
AUDIT_ACTION_ROLE_MIGRATION_UPGRADE = "role_migration_upgrade"
AUDIT_ACTION_ROLE_MIGRATION_DOWNGRADE = "role_migration_downgrade"
AUDIT_ENTITY_TYPE_USER = "user"

MIGRATION_TABLE = "user_role_migrations"
SNAPSHOT_TABLE = "role_migration_snapshots"


def _load_manifest() -> dict[str, str]:
    """Parse and shape-validate MEP_PR10_ROLE_MAPPING. Only ever called
    when at least one ambiguous-role user exists. Returns {employee_code:
    target_role}. Raises RuntimeError (never silently proceeds) on any
    structural problem -- missing, malformed JSON, wrong shape, duplicate
    employee_code, or an unrecognized target role. Does NOT check whether
    each employee_code's *current* role is actually ambiguous -- that
    requires a database lookup and is validated separately in upgrade(),
    against real current state, immediately after this returns."""
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
        # There is no pre-PR10 data to remap in that path, and this
        # migration's provenance tables are meaningless against a
        # database with no pre-PR10 history.
        return

    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS legacy_role_name VARCHAR(50)")

    # This migration's own downgrade authority (see module docstring,
    # points 1-2). Created here so both exist before any row is written to
    # either below; fully dropped by downgrade(), so no other revision or
    # application code may ever come to depend on them.
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {SNAPSHOT_TABLE} ("
        "id UUID PRIMARY KEY, "
        "revision VARCHAR(64) NOT NULL, "
        "legacy_role_id UUID NOT NULL, "
        "legacy_role_name VARCHAR(50) NOT NULL, "
        "legacy_role_permissions JSONB NOT NULL, "
        "snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        f"CONSTRAINT uq_{SNAPSHOT_TABLE}_revision_role UNIQUE (revision, legacy_role_id)"
        ")"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} ("
        "id UUID PRIMARY KEY, "
        "user_id UUID NOT NULL REFERENCES users(id), "
        "revision VARCHAR(64) NOT NULL, "
        "legacy_role VARCHAR(50) NOT NULL, "
        "legacy_role_id UUID NOT NULL, "
        "migrated_role VARCHAR(50) NOT NULL, "
        "migrated_role_id UUID NOT NULL, "
        "migrated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        f"CONSTRAINT uq_{MIGRATION_TABLE}_user_revision UNIQUE (user_id, revision)"
        ")"
    )

    # Step 1: capture every user's current role name before anything is
    # rewritten -- migration provenance, mirrors legacy_status (PR7).
    op.execute(
        "UPDATE users SET legacy_role_name = roles.name "
        "FROM roles WHERE users.role_id = roles.id AND users.legacy_role_name IS NULL"
    )

    # Step 2: identify every ambiguous-role user, by their CURRENT role,
    # before anything is rewritten -- this is also the authoritative set
    # a manifest entry is checked against below (never just "does this
    # employee_code exist").
    ambiguous_rows = bind.execute(
        sa.text(
            "SELECT users.id AS id, users.employee_code AS employee_code, "
            "users.role_id AS legacy_role_id, roles.name AS role_name "
            "FROM users JOIN roles ON users.role_id = roles.id "
            "WHERE roles.name = ANY(:ambiguous)"
        ),
        {"ambiguous": list(AMBIGUOUS_LEGACY_ROLES)},
    ).mappings().all()
    ambiguous_by_code = {row["employee_code"]: row for row in ambiguous_rows}

    # Step 3: validate the ambiguous-role mapping manifest BEFORE any role
    # is rewritten. Fails closed -- never guesses, never proceeds
    # partially, and never lets a manifest entry reach a user whose
    # current role isn't genuinely ambiguous -- an entry naming a
    # safely-auto-mapped admin/viewer account, or an account that already
    # holds a confirmed role, is rejected exactly like an entry naming a
    # nonexistent account.
    manifest: dict[str, str] = {}
    if ambiguous_rows:
        manifest = _load_manifest()
        unresolved = sorted(set(ambiguous_by_code) - set(manifest))
        if unresolved:
            raise RuntimeError(
                "Migration 0009 aborted: MEP_PR10_ROLE_MAPPING does not cover every ambiguous-role "
                f"user. Unresolved employee_code(s): {unresolved}. No role was changed."
            )

    if manifest:
        known_codes = {
            row[0] for row in bind.execute(sa.text("SELECT employee_code FROM users")).all()
        }
        unknown_refs = sorted(set(manifest) - known_codes)
        if unknown_refs:
            raise RuntimeError(
                "Migration 0009 aborted: MEP_PR10_ROLE_MAPPING references employee_code(s) that do "
                f"not exist: {unknown_refs}. No role was changed."
            )

        non_ambiguous_refs = sorted(set(manifest) - set(ambiguous_by_code) - set(unknown_refs))
        if non_ambiguous_refs:
            raise RuntimeError(
                "Migration 0009 aborted: MEP_PR10_ROLE_MAPPING names employee_code(s) whose current "
                f"role is not one of the ambiguous legacy roles ({', '.join(AMBIGUOUS_LEGACY_ROLES)}): "
                f"{non_ambiguous_refs}. The mapping manifest may only remap an ambiguous-role account "
                "-- it must never override the safe automatic admin/viewer mapping or a user who "
                "already holds a confirmed role. No role was changed."
            )

    # Step 4: snapshot every legacy role row that actually exists, EXACTLY
    # (id, name, permissions) -- before the new 3-role model is created or
    # any legacy role is touched. Whatever subset of the 5 legacy names
    # has a row here is what gets snapshotted; never assumed to be all 5.
    legacy_role_rows = bind.execute(
        sa.text("SELECT id, name, permissions FROM roles WHERE name = ANY(:legacy)"),
        {"legacy": list(ALL_LEGACY_ROLES)},
    ).mappings().all()
    for row in legacy_role_rows:
        bind.execute(
            sa.text(
                f"INSERT INTO {SNAPSHOT_TABLE} "
                "(id, revision, legacy_role_id, legacy_role_name, legacy_role_permissions) "
                "VALUES (:id, :revision, :legacy_role_id, :legacy_role_name, CAST(:legacy_role_permissions AS jsonb))"
            ),
            {
                "id": str(uuid.uuid4()),
                "revision": revision,
                "legacy_role_id": row["id"],
                "legacy_role_name": row["name"],
                "legacy_role_permissions": json.dumps(row["permissions"]),
            },
        )

    # Step 5: insert the 3 confirmed role rows if not already present.
    for name in NEW_ROLE_NAMES:
        exists = bind.execute(sa.text("SELECT 1 FROM roles WHERE name = :name"), {"name": name}).first()
        if not exists:
            bind.execute(
                sa.text("INSERT INTO roles (id, name, permissions) VALUES (:id, :name, '{}'::jsonb)"),
                {"id": str(uuid.uuid4()), "name": name},
            )
    new_role_ids: dict[str, str] = {
        row["name"]: row["id"]
        for row in bind.execute(
            sa.text("SELECT id, name FROM roles WHERE name = ANY(:names)"), {"names": list(NEW_ROLE_NAMES)}
        ).mappings().all()
    }

    # Step 6: resolve the complete, exact set of role changes this
    # upgrade will perform -- from real current state only, never assumed
    # -- combining the safe automatic mapping and the validated manifest.
    role_changes: list[dict] = []

    safe_rows = bind.execute(
        sa.text(
            "SELECT users.id AS id, users.employee_code AS employee_code, "
            "users.role_id AS legacy_role_id, roles.name AS role_name "
            "FROM users JOIN roles ON users.role_id = roles.id WHERE roles.name = ANY(:safe)"
        ),
        {"safe": list(SAFE_LEGACY_ROLE_MAPPING)},
    ).mappings().all()
    for row in safe_rows:
        role_changes.append(
            {
                "user_id": row["id"],
                "employee_code": row["employee_code"],
                "legacy_role": row["role_name"],
                "legacy_role_id": row["legacy_role_id"],
                "migrated_role": SAFE_LEGACY_ROLE_MAPPING[row["role_name"]],
            }
        )

    for row in ambiguous_rows:
        target = manifest.get(row["employee_code"])
        if target is None:
            continue  # unreachable: validated above that every ambiguous user is covered
        role_changes.append(
            {
                "user_id": row["id"],
                "employee_code": row["employee_code"],
                "legacy_role": row["role_name"],
                "legacy_role_id": row["legacy_role_id"],
                "migrated_role": target,
            }
        )

    # Step 7: for every resolved change, write this migration's downgrade
    # metadata and audit provenance, THEN update the user's role -- all
    # three in the same statement sequence, inside this revision's single
    # transaction, so a failure writing either record prevents that
    # user's role rewrite (and every other pending change in this run)
    # from being committed at all.
    for change in role_changes:
        migrated_role_id = new_role_ids[change["migrated_role"]]

        bind.execute(
            sa.text(
                f"INSERT INTO {MIGRATION_TABLE} "
                "(id, user_id, revision, legacy_role, legacy_role_id, migrated_role, migrated_role_id) "
                "VALUES (:id, :user_id, :revision, :legacy_role, :legacy_role_id, :migrated_role, :migrated_role_id)"
            ),
            {
                "id": str(uuid.uuid4()),
                "user_id": change["user_id"],
                "revision": revision,
                "legacy_role": change["legacy_role"],
                "legacy_role_id": change["legacy_role_id"],
                "migrated_role": change["migrated_role"],
                "migrated_role_id": migrated_role_id,
            },
        )

        bind.execute(
            sa.text(
                "INSERT INTO audit_logs "
                "(id, user_id, action, entity_type, entity_id, before_data, after_data, "
                "correlation_id, created_at) "
                "VALUES (:id, NULL, :action, :entity_type, :entity_id, "
                "CAST(:before_data AS jsonb), CAST(:after_data AS jsonb), :correlation_id, now())"
            ),
            {
                "id": str(uuid.uuid4()),
                "action": AUDIT_ACTION_ROLE_MIGRATION_UPGRADE,
                "entity_type": AUDIT_ENTITY_TYPE_USER,
                "entity_id": change["user_id"],
                # user_id is deliberately NULL, never a fabricated
                # authenticated actor -- this row's action/entity_type
                # combination, not user_id, is what marks it as a
                # system/migration event (see module docstring, point 3).
                "before_data": json.dumps({"role": change["legacy_role"]}),
                "after_data": json.dumps({"role": change["migrated_role"], "revision": revision}),
                "correlation_id": revision,
            },
        )

        bind.execute(
            sa.text("UPDATE users SET role_id = :migrated_role_id WHERE id = :user_id"),
            {"migrated_role_id": migrated_role_id, "user_id": change["user_id"]},
        )

    # Step 8: verify (never assume) that no user still references a legacy
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

    # ------------------------------------------------------------------
    # Full preflight -- gather everything needed, write nothing yet. Every
    # check below must pass for EVERY affected user/role before this
    # migration performs a single write (Codex review, blocker H3): a
    # legitimate post-upgrade role change is never overwritten, and a
    # restoration is never attempted without the exact original row to
    # restore.
    # ------------------------------------------------------------------

    current_new_role_users = bind.execute(
        sa.text(
            "SELECT u.id AS user_id, u.employee_code AS employee_code, "
            "r.id AS current_role_id, r.name AS current_role "
            "FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name = ANY(:new_roles)"
        ),
        {"new_roles": list(NEW_ROLE_NAMES)},
    ).mappings().all()

    migrated_rows = bind.execute(
        sa.text(
            f"SELECT user_id, legacy_role, legacy_role_id, migrated_role, migrated_role_id "
            f"FROM {MIGRATION_TABLE} WHERE revision = :revision"
        ),
        {"revision": revision},
    ).mappings().all()
    migrated_by_user = {row["user_id"]: row for row in migrated_rows}

    # 1. Every user currently holding a confirmed role must have this
    # revision's per-user metadata -- otherwise there is nothing true to
    # restore them to (e.g. a user created after this migration's upgrade).
    missing_metadata = [row for row in current_new_role_users if row["user_id"] not in migrated_by_user]
    if missing_metadata:
        affected = sorted(row["employee_code"] for row in missing_metadata)
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: {len(missing_metadata)} user(s) hold a confirmed "
            f"3-role-model role but have no {MIGRATION_TABLE} record for this revision (created "
            "after this migration's upgrade, or never migrated by it), so there is nothing true to "
            f"restore them to: {affected}. Back up and hand-resolve these rows before downgrading, "
            "or prefer a forward fix instead. No role was changed."
        )

    # 2. Every migrated user must still hold EXACTLY the role id this
    # migration assigned them -- compared by id, never by name, so a
    # same-named-but-different role could never slip past this check.
    diverged = [
        row
        for row in current_new_role_users
        if row["current_role_id"] != migrated_by_user[row["user_id"]]["migrated_role_id"]
    ]
    if diverged:
        affected = sorted(row["employee_code"] for row in diverged)
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: {len(diverged)} user(s) no longer hold the role this "
            f"migration assigned them -- their role changed after upgrade (e.g. via the ordinary "
            f"POST/PATCH /api/v1/users API): {affected}. Restoring the pre-migration role would "
            "silently discard that legitimate change. No role was changed."
        )

    # 3. Every legacy_role_id this revision's user metadata refers to must
    # have a matching row snapshot -- otherwise a role name alone would
    # have to be trusted to reconstruct the original row, which is exactly
    # the lossy behavior this fix replaces. UNIQUE(revision, legacy_role_id)
    # on the snapshot table makes a duplicate/inconsistent snapshot for the
    # same role structurally impossible, not merely checked here.
    snapshot_rows = bind.execute(
        sa.text(
            f"SELECT legacy_role_id, legacy_role_name, legacy_role_permissions "
            f"FROM {SNAPSHOT_TABLE} WHERE revision = :revision"
        ),
        {"revision": revision},
    ).mappings().all()
    snapshot_by_id = {row["legacy_role_id"]: row for row in snapshot_rows}

    referenced_legacy_ids = {row["legacy_role_id"] for row in migrated_rows}
    missing_snapshot_ids = sorted(str(i) for i in (referenced_legacy_ids - set(snapshot_by_id)))
    if missing_snapshot_ids:
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: no {SNAPSHOT_TABLE} record exists for legacy "
            f"role id(s) {missing_snapshot_ids} that this revision's own user metadata refers to -- "
            "cannot losslessly reconstruct the original role row. No role was changed."
        )

    # 4. Restoring a snapshotted role must never collide with some other,
    # unrelated role that legitimately exists right now under that id.
    existing_role_ids = {row[0] for row in bind.execute(sa.text("SELECT id FROM roles")).all()}
    colliding_ids = sorted(str(i) for i in (set(snapshot_by_id) & existing_role_ids))
    if colliding_ids:
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: role id(s) {colliding_ids} already exist in `roles` "
            "and would collide with a snapshotted legacy role being restored. No role was changed."
        )

    # ------------------------------------------------------------------
    # Every precondition passed -- perform the exact restoration.
    # ------------------------------------------------------------------

    # 5. Recreate every snapshotted legacy role row EXACTLY -- the same
    # id, name, and permissions it had before upgrade. Every role that was
    # snapshotted is restored, not only the ones a currently-migrated user
    # happens to reference, so the `roles` table itself round-trips fully.
    for snap in snapshot_rows:
        bind.execute(
            sa.text("INSERT INTO roles (id, name, permissions) VALUES (:id, :name, CAST(:permissions AS jsonb))"),
            {
                "id": snap["legacy_role_id"],
                "name": snap["legacy_role_name"],
                "permissions": json.dumps(snap["legacy_role_permissions"]),
            },
        )

    # 6. Per restored user: write downgrade audit provenance, then restore
    # role_id to the EXACT original role id (never inferred from the role
    # name, never a freshly generated id).
    for row in current_new_role_users:
        meta = migrated_by_user[row["user_id"]]

        bind.execute(
            sa.text(
                "INSERT INTO audit_logs "
                "(id, user_id, action, entity_type, entity_id, before_data, after_data, "
                "correlation_id, created_at) "
                "VALUES (:id, NULL, :action, :entity_type, :entity_id, "
                "CAST(:before_data AS jsonb), CAST(:after_data AS jsonb), :correlation_id, now())"
            ),
            {
                "id": str(uuid.uuid4()),
                "action": AUDIT_ACTION_ROLE_MIGRATION_DOWNGRADE,
                "entity_type": AUDIT_ENTITY_TYPE_USER,
                "entity_id": row["user_id"],
                "before_data": json.dumps({"role": meta["migrated_role"]}),
                "after_data": json.dumps({"role": meta["legacy_role"], "revision": revision}),
                "correlation_id": revision,
            },
        )

        bind.execute(
            sa.text("UPDATE users SET role_id = :legacy_role_id WHERE id = :user_id"),
            {"legacy_role_id": meta["legacy_role_id"], "user_id": row["user_id"]},
        )

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
    # This migration's own downgrade-authority tables -- dropped entirely,
    # not merely emptied, since no other revision or application code may
    # ever depend on them (see module docstring, points 1-2).
    op.execute(f"DROP TABLE IF EXISTS {MIGRATION_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {SNAPSHOT_TABLE}")
