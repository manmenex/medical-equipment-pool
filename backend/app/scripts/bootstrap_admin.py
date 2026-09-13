"""Production-safe first-administrator bootstrap.

PR24B (`docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §17): the
existing `backend/app/scripts/seed.py` creates a hardcoded
`ADMIN001`/`Admin@12345` account plus demo departments/wards/equipment --
confirmed unsafe for production and never intended for it. This script is
the deployment-foundation replacement for production use only: it creates
exactly one initial administrator, with no hardcoded password and no
demo/sample data, and refuses to run if an administrator already exists.

Usage (controlled operator execution, not exposed over HTTP -- see the
module docstring's own "no unauthenticated bootstrap endpoint" rule in the
design doc):

    python -m app.scripts.bootstrap_admin --employee-code ADMIN001 \\
        --email admin@hospital.local --full-name "System Administrator"

The temporary password is generated securely and printed exactly once to
stdout -- it is never logged, written to a file, or stored anywhere in
plaintext.

Forced first-login rotation now exists and this script uses it: the created
account carries `must_change_password=True`, and the only thing that clears
it is `auth_service.change_password`, which first proves the caller knows
the current password. (This paragraph replaces an earlier note saying no
such flag existed -- it does now, and the operator is no longer relied upon
to remember.)
"""
import argparse
import asyncio
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import DomainError
from app.core.security import hash_password
from app.crud import audit as audit_crud
from app.db.session import AsyncSessionLocal
from app.models.user import ROLE_ADMINISTRATOR, Role, User
from app.services.password_policy import validate_password

# Drawn from the same set the Owner restricted passwords to
# (auth_service.ALLOWED_PASSWORD_DESCRIPTION): English letters and digits.
#
# This used to be `secrets.token_urlsafe`, whose base64url alphabet also
# includes "-" and "_". That handed the operator a one-time password
# containing characters the application then refuses in the replacement --
# the very first credential anyone types, breaking the rule it is about to
# teach them, on the phone keyboard the restriction exists to spare.
#
# 32 characters from a 62-character alphabet is ~190 bits, against ~192 from
# the token_urlsafe(24) it replaces. Two bits, for a credential that is used
# once and immediately rotated. `secrets.choice` is uniform and
# cryptographically sound; a modulo over `secrets.randbelow` would not be.
_TEMP_PASSWORD_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_TEMP_PASSWORD_LENGTH = 32

# Each draw satisfies the policy with probability ~0.996; 20 attempts fail
# with probability ~1e-46. The bound exists so a future policy no random
# string can satisfy raises rather than spins forever.
_TEMP_PASSWORD_MAX_ATTEMPTS = 20


def generate_temporary_password(*identifiers: str | None) -> str:
    """A one-time password that satisfies the application's own rules.

    Draw-and-verify against `validate_password` rather than hand-reasoning
    about which rules a random string happens to satisfy. That reasoning was
    wrong on the first attempt: 32 characters drawn uniformly from a
    62-character alphabet contain no digit about 0.4% of the time, which the
    "must contain a digit" rule refuses -- so roughly one bootstrap in 280
    would have handed the operator a password the application would not let
    them replace with a like-for-like one, and no amount of staring at the
    generator would have surfaced it.

    Verifying against the real validator means the generator cannot drift
    from the policy again, whatever the policy becomes next.
    """
    for _ in range(_TEMP_PASSWORD_MAX_ATTEMPTS):
        candidate = "".join(
            secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(_TEMP_PASSWORD_LENGTH)
        )
        try:
            validate_password(candidate, identifiers=identifiers)
        except DomainError:
            continue
        return candidate
    # Unreachable short of a broken RNG or a policy no random string can
    # satisfy. Failing loudly beats returning a password the application
    # will then refuse.
    raise RuntimeError(
        "Could not generate a temporary password satisfying the password policy after "
        f"{_TEMP_PASSWORD_MAX_ATTEMPTS} attempts."
    )


class BootstrapRefused(RuntimeError):
    """Raised when bootstrap must not proceed (administrator already exists)."""


async def _lock_administrator_role(db) -> Role:
    """Serializes concurrent bootstrap attempts on the `administrator`
    `roles` row (already created by migration 0009_role_consolidation.py
    on every deployment) -- the same `SELECT ... FOR UPDATE`-on-PostgreSQL/
    no-op-on-SQLite convention every other concurrency-sensitive CRUD
    module in this codebase already follows (e.g.
    `app/crud/legacy_reconciliation.py`, `app/crud/equipment.py`), rather
    than inventing a new locking primitive (e.g. a Postgres advisory
    lock) for this one case."""
    stmt = select(Role).where(Role.name == ROLE_ADMINISTRATOR)
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()
    if role is None:
        raise RuntimeError(
            f"No {ROLE_ADMINISTRATOR!r} role found -- run `alembic upgrade head` first "
            "(migration 0009_role_consolidation creates it)."
        )
    return role


async def _administrator_exists(db, *, role_id) -> bool:
    result = await db.execute(select(User.id).where(User.role_id == role_id).limit(1))
    return result.scalar_one_or_none() is not None


async def bootstrap_admin(*, employee_code: str, email: str, full_name: str) -> tuple[User, str]:
    """Creates exactly one initial administrator inside a single
    transaction. Raises `BootstrapRefused` (no changes made) if an
    administrator already exists -- including one created by a
    concurrent invocation that won the `administrator` role-row lock
    first."""
    temp_password = generate_temporary_password(employee_code, full_name, email)

    async with AsyncSessionLocal() as db:
        admin_role = await _lock_administrator_role(db)

        if await _administrator_exists(db, role_id=admin_role.id):
            raise BootstrapRefused(
                "An administrator already exists. Refusing to bootstrap a second one. "
                "Use the existing administrator account (or an existing administrator's "
                "PATCH /users/{id} capability) to manage further users."
            )

        user = User(
            employee_code=employee_code,
            full_name=full_name,
            email=email,
            password_hash=hash_password(temp_password),
            role_id=admin_role.id,
            # The one-time password below is printed to a console and,
            # realistically, written down. It is a temporary credential by
            # construction, so the account starts out required to replace
            # it -- cleared only by auth_service.change_password, which
            # first proves the caller knows it.
            must_change_password=True,
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError as exc:
            # Defensive: the role-row lock above already serializes
            # concurrent bootstrap attempts on PostgreSQL, so this should
            # only fire if employee_code/email collided with a
            # *different* pre-existing (non-administrator) user, or on
            # SQLite where the lock above is a no-op. Either way: no
            # partial state survives (the whole session is discarded
            # below), and the operator gets an actionable message instead
            # of a raw IntegrityError/stack trace.
            await db.rollback()
            raise BootstrapRefused(
                f"Could not create the administrator: employee_code={employee_code!r} or "
                f"email={email!r} is already in use by another user. Choose different "
                "identifiers and retry."
            ) from exc

        # user_id=None is deliberate, not a fabricated actor: no
        # authenticated User exists yet at this point in a fresh
        # deployment (AuditLog.user_id is nullable exactly for cases like
        # this -- see app/models/audit.py). Never audits the temporary
        # password itself.
        await audit_crud.create(
            db,
            user_id=None,
            action="ADMIN_BOOTSTRAP",
            entity_type="user",
            entity_id=user.id,
            after_data={"employee_code": employee_code, "email": email, "full_name": full_name},
        )
        await db.commit()
        await db.refresh(user)
        return user, temp_password


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--employee-code", required=True, help="unique staff identifier for the new administrator")
    parser.add_argument("--email", required=True, help="unique email address for the new administrator")
    parser.add_argument(
        "--full-name", default="System Administrator", help="display name (default: 'System Administrator')"
    )
    args = parser.parse_args()

    try:
        user, temp_password = await bootstrap_admin(
            employee_code=args.employee_code, email=args.email, full_name=args.full_name
        )
    except BootstrapRefused as exc:
        print(f"Bootstrap refused: {exc}")
        raise SystemExit(1) from exc

    print("Administrator created.")
    print(f"  employee_code: {user.employee_code}")
    print(f"  email:         {user.email}")
    print(f"  temporary password (shown once, not stored anywhere else): {temp_password}")
    print(
        "Log in with this password immediately, then change it via the existing "
        "user-management password-update capability -- this repository does not yet "
        "enforce forced first-login rotation."
    )


if __name__ == "__main__":
    asyncio.run(main())
