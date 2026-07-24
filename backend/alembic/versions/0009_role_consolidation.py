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
  4. `confirmed_role_ownership` (Codex review round 3, PR #36, the
     remaining blocker) -- one row per confirmed role this revision
     actually deals with, recording whether upgrade() *created* that role
     row or *reused* one that already existed under that name before this
     migration ever ran. Role name alone is never treated as proof of
     ownership: this table is keyed by the role's exact primary key, not
     its name, so a same-named row that turns out to have a different id
     than what this table recorded is never assumed to be the same row.
     downgrade() consults this table, never `roles.name`, to decide what
     it may delete -- see the dedicated section below.

The pre-existing `users.legacy_role_name` column (added by this same
migration, mirroring `BorrowTransaction.legacy_status`'s Roadmap PR7
pattern) is still populated for every user before any rewrite, as a
simple, single-column, human-readable record of "what role did this user
have going into Roadmap PR10" -- but it is provenance-only, never read by
the application, and (unlike `user_role_migrations`/
`role_migration_snapshots`) is not downgrade()'s authority, since a role
name alone cannot losslessly reconstruct the original row identity or
distinguish "still safe to restore" from "diverged after upgrade."

Confirmed-role ownership (Codex review round 3 on PR #36, the remaining
blocker): a deployment's `roles` table may already contain a row named
`administrator`, `equipment_pool_staff`, or `read_only` before this
migration ever runs (e.g. a partially-migrated environment, or an
operator who pre-created these rows). upgrade() must never treat "this
row's name matches a confirmed role" as "this migration owns this row" --
that conflation is exactly what let round-2's downgrade() unconditionally
`DELETE FROM roles WHERE name = ANY(the 3 confirmed names)`, destroying a
pre-existing row (and, transitively, any of its own pre-existing data)
that upgrade() never created. Fixed by recording, for every confirmed
role upgrade() looks up or creates, exactly one `confirmed_role_ownership`
row (see point 4 above) capturing whether that exact row existed before
upgrade or was created by it. downgrade() then:
  - deletes a role row only when its own ownership record for this
    revision says `created_by_migration = true`, matched by exact role
    id -- never by scanning for a name;
  - never deletes a row whose ownership record says
    `existed_before_upgrade = true`; instead it restores that row's
    pre-upgrade `permissions` (captured in the same ownership row) onto
    its own unchanged id, and otherwise leaves it exactly as it was;
  - aborts before any write if a currently-confirmed role has no
    ownership record for this revision, or if that record's role id does
    not match the role currently sitting under that name (proof, not
    inference, of "this is the same row upgrade() reasoned about");
  - aborts before any write if a `created_by_migration = true` role still
    has a *non-migrated* user referencing it (i.e. a user who is not in
    this revision's own `user_role_migrations`) -- upgrade() never
    deletes the row itself, so the only other foreign-key reference to
    `roles.id` in this schema is `users.role_id` (confirmed by inspecting
    `backend/app/models/user.py`; no other table references `roles`),
    which is exactly what this check inspects.
A `CHECK (existed_before_upgrade <> created_by_migration)` constraint
makes the two ownership flags structurally incapable of ever agreeing or
both being false/true for the same row -- there is no code path, correct
or corrupted, that can persist a contradictory pair. `UNIQUE(revision,
role_id)` and `UNIQUE(revision, role_name)` together make a duplicate or
inconsistent ownership record for the same role, in either dimension,
structurally impossible rather than merely checked at runtime.

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
  - confirmed_role_ownership  new table; downgrade()'s sole authority for
                                which confirmed-role rows it may ever
                                delete (see point 4 above and the
                                dedicated section below). Created and
                                fully dropped by this revision's upgrade/
                                downgrade respectively.
  - audit_logs                gains one row per user this migration
                                changes, in either direction (no column
                                change -- the table's existing nullable
                                `user_id` and JSONB before_data/after_data
                                columns are sufficient).
  - roles                     each confirmed role is inserted only if no
                                row of that name already exists; the
                                legacy rows actually present are deleted
                                once no user references them; a CHECK
                                constraint then restricts roles.name to
                                exactly the 3 confirmed values (defense in
                                depth -- the application layer, via
                                app.models.user.ALL_ROLES and
                                app.schemas.master_data.RoleName, is still
                                the primary gate). downgrade() deletes
                                only the confirmed-role rows it can prove
                                (via confirmed_role_ownership) it created.

No equipment/transaction lifecycle, dispatch/receipt/ward-correction
contract, or unrelated schema change is part of this migration.

Design note (Codex review rounds 2 and 3, migration design constraints):
PR10 is unmerged, so every fix round is made directly in this revision
file rather than stacked as a follow-up migration -- there is no
already-deployed copy of 0009 anywhere for a stacked fix to be safer
against, and stacking one here would only add an avoidable extra revision
to review. The upgrade step order below adapts the reviewed suggestion in
one place: capturing a user's `migrated_role_id` genuinely requires the
new role rows to already exist (their ids are generated at insert time),
so the per-user `user_role_migrations` row is written in the same
per-user step that performs the role_id UPDATE (as it already was before
this fix round), immediately after the role-level
`role_migration_snapshots` capture and the confirmed-role-model
creation/reuse that necessarily precedes it -- not before them. The
*role*-level snapshot (point 1 above), which has no such dependency, is
still taken first, before any roles-table mutation.

Round 3's "validate the pre-existing row is safe to use" requirement is
implemented as narrowly as the actual schema supports: `roles.permissions`
is a plain JSONB column with no other structural constraint anywhere in
this codebase, so the only concrete, schema-grounded conflict upgrade()
can detect is a pre-existing row whose `permissions` value does not
decode as a JSON object (the shape `app.models.user.Role.permissions`
requires) -- upgrade() aborts before any write if that happens, rather
than inventing a business rule this schema does not actually enforce.

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
OWNERSHIP_TABLE = "confirmed_role_ownership"


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
    # downgrade()'s sole authority for whether it may ever delete a
    # confirmed-role row (see module docstring, point 4 and the dedicated
    # "Confirmed-role ownership" section) -- role name is never proof of
    # ownership, only an exact (revision, role_id) match here is.
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {OWNERSHIP_TABLE} ("
        "id UUID PRIMARY KEY, "
        "revision VARCHAR(64) NOT NULL, "
        "role_id UUID NOT NULL, "
        "role_name VARCHAR(50) NOT NULL, "
        "existed_before_upgrade BOOLEAN NOT NULL, "
        "created_by_migration BOOLEAN NOT NULL, "
        "pre_upgrade_permissions JSONB, "
        "snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        f"CONSTRAINT uq_{OWNERSHIP_TABLE}_revision_role UNIQUE (revision, role_id), "
        f"CONSTRAINT uq_{OWNERSHIP_TABLE}_revision_name UNIQUE (revision, role_name), "
        f"CONSTRAINT ck_{OWNERSHIP_TABLE}_flags CHECK (existed_before_upgrade <> created_by_migration)"
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

    # Step 5: for each confirmed role, create it if no row of that name
    # exists yet, or reuse the exact pre-existing row if one does -- and
    # record ownership provenance either way (Codex review round 3, the
    # remaining blocker: role name is never proof that this migration may
    # later delete a row, only confirmed_role_ownership is).
    new_role_ids: dict[str, str] = {}
    for name in NEW_ROLE_NAMES:
        existing = bind.execute(
            sa.text("SELECT id, permissions FROM roles WHERE name = :name"), {"name": name}
        ).mappings().first()

        if existing is None:
            role_id = str(uuid.uuid4())
            bind.execute(
                sa.text("INSERT INTO roles (id, name, permissions) VALUES (:id, :name, '{}'::jsonb)"),
                {"id": role_id, "name": name},
            )
            bind.execute(
                sa.text(
                    f"INSERT INTO {OWNERSHIP_TABLE} "
                    "(id, revision, role_id, role_name, existed_before_upgrade, created_by_migration, "
                    "pre_upgrade_permissions) "
                    "VALUES (:id, :revision, :role_id, :role_name, false, true, NULL)"
                ),
                {"id": str(uuid.uuid4()), "revision": revision, "role_id": role_id, "role_name": name},
            )
        else:
            role_id = existing["id"]
            # "Validate the pre-existing row is safe to use" (round 3): the
            # only structural requirement this schema places on
            # `permissions` is that it decode as a JSON object -- see the
            # module docstring's design note for why nothing stronger is
            # checked here.
            if not isinstance(existing["permissions"], dict):
                raise RuntimeError(
                    f"Migration 0009 aborted: a pre-existing '{name}' role row (id={existing['id']}) has a "
                    f"permissions value that is not a JSON object ({existing['permissions']!r}), so it cannot "
                    "be safely reused by this migration. No role was changed."
                )
            bind.execute(
                sa.text(
                    f"INSERT INTO {OWNERSHIP_TABLE} "
                    "(id, revision, role_id, role_name, existed_before_upgrade, created_by_migration, "
                    "pre_upgrade_permissions) "
                    "VALUES (:id, :revision, :role_id, :role_name, true, false, CAST(:permissions AS jsonb))"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "revision": revision,
                    "role_id": role_id,
                    "role_name": name,
                    "permissions": json.dumps(existing["permissions"]),
                },
            )

        new_role_ids[name] = role_id

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

    # Codex review round 3, the remaining blocker: this migration's own
    # ownership provenance for every confirmed role it looked up or
    # created (see module docstring, point 4 and the "Confirmed-role
    # ownership" section). This is downgrade()'s sole authority for what
    # it may ever delete -- role name is never treated as ownership proof.
    ownership_rows = bind.execute(
        sa.text(
            f"SELECT role_id, role_name, existed_before_upgrade, created_by_migration, "
            f"pre_upgrade_permissions FROM {OWNERSHIP_TABLE} WHERE revision = :revision"
        ),
        {"revision": revision},
    ).mappings().all()
    ownership_by_name = {row["role_name"]: row for row in ownership_rows}
    ownership_by_role_id = {row["role_id"]: row for row in ownership_rows}

    current_confirmed_roles = bind.execute(
        sa.text("SELECT id, name FROM roles WHERE name = ANY(:new_roles)"),
        {"new_roles": list(NEW_ROLE_NAMES)},
    ).mappings().all()

    # 1. Every confirmed-role row currently in `roles` must have this
    # revision's own ownership record -- otherwise downgrade cannot prove
    # whether it may ever delete that row, and must not guess from its
    # name alone.
    missing_ownership = [row for row in current_confirmed_roles if row["name"] not in ownership_by_name]
    if missing_ownership:
        affected = sorted(f"{row['name']} (id={row['id']})" for row in missing_ownership)
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: {len(missing_ownership)} confirmed-role row(s) have no "
            f"{OWNERSHIP_TABLE} record for this revision, so downgrade cannot prove whether it created "
            f"them: {affected}. No role was changed."
        )

    # 2. The role currently sitting under a confirmed name must be the
    # EXACT same row this revision's ownership record describes -- a
    # name match alone is never treated as proof of the same row (a
    # different row could have been deleted and recreated under the same
    # name by something else entirely).
    id_mismatches = [
        row for row in current_confirmed_roles if ownership_by_name[row["name"]]["role_id"] != row["id"]
    ]
    if id_mismatches:
        affected = sorted(
            f"{row['name']}: ownership expects id={ownership_by_name[row['name']]['role_id']}, "
            f"found id={row['id']}"
            for row in id_mismatches
        )
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: {len(id_mismatches)} confirmed-role name(s) are currently "
            f"held by a different row than this revision's ownership record describes: {affected}. A "
            "role name match is never treated as ownership proof. No role was changed."
        )

    # 3. Every user currently holding a MIGRATION-CREATED confirmed role
    # must have this revision's per-user metadata. In this schema this one
    # check simultaneously proves two things the review's preflight list
    # asks for separately: (a) there is nothing true to restore such a
    # user to (no metadata), and (b) the role has an "unrelated
    # post-upgrade reference" (`users.role_id` is the only foreign-key
    # reference to `roles.id` in this schema -- see the note after check 7
    # below -- so any user on a migration-created role who is not in this
    # revision's own metadata can only have gotten there via this
    # migration itself or via later, unrelated application usage; there is
    # no third possibility). Either way the role cannot be safely deleted
    # while they reference it. A user on a REUSED pre-existing confirmed
    # role with no metadata is expected and harmless -- this migration
    # never owned that role's assignments and must leave both the role
    # and the user alone.
    missing_metadata = [
        row
        for row in current_new_role_users
        if row["user_id"] not in migrated_by_user and ownership_by_role_id[row["current_role_id"]]["created_by_migration"]
    ]
    if missing_metadata:
        affected = sorted(
            f"role_id={row['current_role_id']} ({row['current_role']}): employee_code={row['employee_code']}"
            for row in missing_metadata
        )
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: {len(missing_metadata)} user(s) hold a migration-created "
            f"confirmed role but have no {MIGRATION_TABLE} record for this revision, so there is nothing "
            f"true to restore them to, and the role cannot be safely deleted while an unrelated reference "
            f"exists: {affected}. Back up and hand-resolve these rows before downgrading, or prefer a "
            "forward fix instead. No role was changed."
        )

    # 4. Every migrated user must still hold EXACTLY the role id this
    # migration assigned them -- compared by id, never by name, so a
    # same-named-but-different role could never slip past this check.
    # Scoped to migrated users only (see point 3 above).
    diverged = [
        row
        for row in current_new_role_users
        if row["user_id"] in migrated_by_user
        and row["current_role_id"] != migrated_by_user[row["user_id"]]["migrated_role_id"]
    ]
    if diverged:
        affected = sorted(row["employee_code"] for row in diverged)
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: {len(diverged)} user(s) no longer hold the role this "
            f"migration assigned them -- their role changed after upgrade (e.g. via the ordinary "
            f"POST/PATCH /api/v1/users API): {affected}. Restoring the pre-migration role would "
            "silently discard that legitimate change. No role was changed."
        )

    # 5. Every legacy_role_id this revision's user metadata refers to must
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

    # 6. Restoring a snapshotted role must never collide with some other,
    # unrelated role that legitimately exists right now under that id.
    existing_role_ids = {row[0] for row in bind.execute(sa.text("SELECT id FROM roles")).all()}
    colliding_ids = sorted(str(i) for i in (set(snapshot_by_id) & existing_role_ids))
    if colliding_ids:
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: role id(s) {colliding_ids} already exist in `roles` "
            "and would collide with a snapshotted legacy role being restored. No role was changed."
        )

    # 7. A reused pre-existing confirmed role must have a complete
    # pre-upgrade snapshot to restore -- should be unreachable given how
    # upgrade() writes this table, checked anyway rather than assumed.
    reused_missing_snapshot = [row for row in ownership_rows if row["existed_before_upgrade"] and row["pre_upgrade_permissions"] is None]
    if reused_missing_snapshot:
        affected = sorted(row["role_name"] for row in reused_missing_snapshot)
        raise RuntimeError(
            f"Migration 0009 downgrade aborted: {len(reused_missing_snapshot)} reused confirmed role(s) "
            f"have no pre-upgrade permissions snapshot recorded, so they cannot be losslessly restored: "
            f"{affected}. This should be unreachable; investigate before retrying. No role was changed."
        )

    # (The review's own "migration-created confirmed roles have no
    # unrelated post-upgrade references" preflight item is exactly check 3
    # above, in this schema: `users.role_id` is the only foreign-key
    # reference to `roles.id` anywhere in this codebase --
    # backend/app/models/user.py; no other table references `roles` -- so
    # a non-migrated user on a migration-created role IS the unrelated
    # reference. There is no second, structurally-distinct case to check.)

    # ------------------------------------------------------------------
    # Every precondition passed -- perform the exact restoration.
    # ------------------------------------------------------------------

    # 8. Recreate every snapshotted legacy role row EXACTLY -- the same
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

    # 9. Restore every REUSED confirmed role's exact pre-upgrade
    # permissions onto its own unchanged id -- the row itself was never
    # deleted, so only its mutable content needs restoring.
    for row in ownership_rows:
        if not row["existed_before_upgrade"]:
            continue
        bind.execute(
            sa.text("UPDATE roles SET permissions = CAST(:permissions AS jsonb) WHERE id = :role_id"),
            {"permissions": json.dumps(row["pre_upgrade_permissions"]), "role_id": row["role_id"]},
        )

    # 10. Per migrated user: write downgrade audit provenance, then
    # restore role_id to the EXACT original role id (never inferred from
    # the role name, never a freshly generated id). A non-migrated user on
    # a reused role (see check 3) is deliberately left untouched here.
    migrated_user_ids = list(migrated_by_user.keys())
    for row in current_new_role_users:
        if row["user_id"] not in migrated_by_user:
            continue
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

    # Sanity check restricted to users this migration actually restored --
    # a non-migrated user legitimately remaining on a reused confirmed
    # role is expected, not an error (see check 3). Skipped entirely (not
    # queried with an empty array parameter) when this revision migrated
    # zero users -- vacuously satisfied, and an empty `= ANY(:param)` array
    # parameter has no element type for the driver to infer.
    if migrated_user_ids:
        remaining = bind.execute(
            sa.text(
                "SELECT count(*) FROM users u JOIN roles r ON u.role_id = r.id "
                "WHERE r.name = ANY(:new_roles) AND u.id = ANY(:migrated_user_ids)"
            ),
            {"new_roles": list(NEW_ROLE_NAMES), "migrated_user_ids": migrated_user_ids},
        ).scalar_one()
        if remaining:
            raise RuntimeError(
                f"Migration 0009 downgrade aborted: {remaining} migrated user(s) still reference a "
                "confirmed 3-role-model role after restoring legacy roles -- this should be unreachable; "
                "investigate before retrying. No confirmed role row was deleted."
            )

    # 11. Delete ONLY the confirmed-role rows this revision's own
    # ownership record proves it created -- by exact role id, never by
    # scanning for a name. A reused pre-existing role is never deleted,
    # regardless of its name.
    for row in ownership_rows:
        if not row["created_by_migration"]:
            continue
        bind.execute(sa.text("DELETE FROM roles WHERE id = :role_id"), {"role_id": row["role_id"]})

    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS legacy_role_name")
    # This migration's own downgrade-authority tables -- dropped entirely,
    # not merely emptied, since no other revision or application code may
    # ever depend on them (see module docstring, points 1, 2, and 4).
    op.execute(f"DROP TABLE IF EXISTS {MIGRATION_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {SNAPSHOT_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {OWNERSHIP_TABLE}")
