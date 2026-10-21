import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import (
    AUDIT_ACTION_ACCOUNT_LOCKED,
    AUDIT_ACTION_LOGIN_FAILURE,
    AUDIT_ACTION_LOGIN_SUCCESS,
    AUDIT_ACTION_LOGOUT,
    AUDIT_ACTION_PASSWORD_CHANGE,
    AUDIT_ACTION_TOKEN_REFRESH,
    AUDIT_ENTITY_AUTH,
    commit_best_effort,
    record_best_effort_audit_event,
)
from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.redis import is_refresh_token_valid, revoke_refresh_token, store_refresh_token
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.crud import user as user_crud
from app.models.user import Role, User
from app.services.password_policy import (  # noqa: F401  (re-exported)
    ALLOWED_PASSWORD_DESCRIPTION,
    MAXIMUM_PASSWORD_BYTES,
    MINIMUM_PASSWORD_LENGTH,
    CommonPasswordError,
    PasswordContainsIdentifierError,
    RepetitivePasswordError,
    WeakPasswordError,
    validate_password,
)


class InvalidCredentialsError(DomainError):
    code = "INVALID_CREDENTIALS"
    status_code = 401


class InvalidRefreshTokenError(DomainError):
    code = "INVALID_REFRESH_TOKEN"
    status_code = 401


class SamePasswordError(DomainError):
    code = "SAME_PASSWORD"
    status_code = 400


class AccountLockedError(DomainError):
    """Too many consecutive failed attempts on this account.

    **This code tells an attacker that the account exists**, which the
    login path otherwise refuses to do (it returns the same
    INVALID_CREDENTIALS for an unknown identifier and a wrong password).
    That is an accepted trade, not an oversight:

      * employee codes in this deployment are printed on badges, so
        "does BME001 exist" is not a secret the API is keeping;
      * the alternative is a ward nurse whose correct password stops
        working with no explanation, mid-shift, who then keeps trying and
        extends the lock. The support call that produces costs more than
        the enumeration it prevents.

    Flipping this to a silent INVALID_CREDENTIALS is a one-line change in
    `authenticate` if the Owner later decides otherwise.
    """

    code = "ACCOUNT_LOCKED"
    status_code = 423


# Owner decision: 5 consecutive failures, locked for 10 minutes, per account.
#
# **The cost this buys, stated plainly: anyone who knows an employee code can
# lock that person out for 10 minutes at will**, by failing five times
# deliberately. That is inherent to per-account lockout -- it is the chosen
# shape, not a defect -- and 10 minutes is short enough that it is a nuisance
# rather than a denial of care. The alternative shapes (per-source-address,
# or exponential backoff without a hard lock) were not chosen.
MAXIMUM_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=10)


# The rules themselves live in app/services/password_policy.py -- they are an
# Owner-owned policy that changes on its own schedule, and keeping them out of
# here means they can be read and tested without a DB session. Re-exported so
# existing importers of these names keep working.
def validate_new_password(new_password: str, *, user: User | None = None) -> None:
    """Applies the password policy, including the account-specific rules.

    `user` is optional only so the policy can be exercised without one; every
    caller in the application passes it, because the identifier rule -- no
    employee code, name or email inside the password -- is the one that
    matters most in a hospital, where a colleague can read the badge.
    """
    identifiers: tuple[str | None, ...] = ()
    if user is not None:
        identifiers = (user.employee_code, user.full_name, user.email)
    validate_password(new_password, identifiers=identifiers)


async def change_password(
    db: AsyncSession,
    user: User,
    *,
    current_password: str,
    new_password: str,
    request: Request | None = None,
) -> User:
    """Replaces the caller's OWN password, having proved they know the
    current one.

    Knowing the current password is required even though the caller already
    holds a valid access token: a token left behind on an unattended
    workstation must not be enough to take an account over permanently.

    On success `must_change_password` is cleared -- this is the only place
    that clears it, so a bootstrap or Administrator-set password cannot
    stop being temporary by any other route.
    """
    # This endpoint verifies the same secret the login path does, so it is
    # throttled by the same counter. Without that, a stolen access token
    # would give an attacker an unlimited oracle for the current password
    # here while /auth/login was locked -- the lockout would be real on one
    # door and decorative on the other.
    if is_locked(user):
        minutes = max(1, round(lock_expires_in_seconds(user) / 60))
        raise AccountLockedError(
            f"This account is temporarily locked after "
            f"{MAXIMUM_FAILED_LOGIN_ATTEMPTS} failed attempts. "
            f"Try again in about {minutes} minute(s)."
        )

    if not verify_password(current_password, user.password_hash):
        await record_best_effort_audit_event(
            db,
            actor_user_id=user.id,
            action=AUDIT_ACTION_LOGIN_FAILURE,
            entity_type=AUDIT_ENTITY_AUTH,
            entity_id=user.id,
            request=request,
        )
        await _record_failed_attempt(db, user, request=request)
        await commit_best_effort(db)
        # Deliberately the same error the login path raises: "wrong current
        # password" and "wrong password" are the same fact about the same
        # secret, and inventing a second code would say more, not less.
        raise InvalidCredentialsError("Current password is incorrect")

    validate_new_password(new_password, user=user)

    if verify_password(new_password, user.password_hash):
        raise SamePasswordError("New password must be different from the current password.")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    # They proved they know the current password to get here, so any
    # accumulated failures were their own typing, not an attack.
    await _clear_failed_attempts(db, user)

    await record_best_effort_audit_event(
        db,
        actor_user_id=user.id,
        action=AUDIT_ACTION_PASSWORD_CHANGE,
        entity_type=AUDIT_ENTITY_AUTH,
        entity_id=user.id,
        request=request,
    )
    # NOT best-effort: unlike last_login_at, a password change that is not
    # durably persisted must not be reported as successful. The caller would
    # believe their new password works and discover otherwise at the next
    # login, possibly after discarding the old one.
    await db.commit()
    return user


def is_locked(user: User, *, now: datetime | None = None) -> bool:
    """A lock expires by being in the past, with nothing to clear it.

    No scheduled job, no cron, no cleanup task -- deliberately. Anything
    that has to run to release a lock is something that can fail quietly
    and leave a nurse locked out through a shift.
    """
    if user.locked_until is None:
        return False
    reference = now or datetime.now(timezone.utc)
    stored = user.locked_until
    if stored.tzinfo is None:
        # SQLite round-trips naive datetimes; PostgreSQL returns aware ones.
        # Treating a naive value as anything but UTC would make the lock
        # either permanent or instantly expired depending on the server's
        # local offset.
        stored = stored.replace(tzinfo=timezone.utc)
    return stored > reference


def lock_expires_in_seconds(user: User, *, now: datetime | None = None) -> int:
    """Whole seconds until the lock lifts, floored at 0, for the message."""
    if not is_locked(user, now=now):
        return 0
    reference = now or datetime.now(timezone.utc)
    stored = user.locked_until
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)
    return max(0, int((stored - reference).total_seconds()))


async def _record_failed_attempt(
    db: AsyncSession, user: User, *, request: Request | None = None
) -> None:
    """Counts one failure against the account, locking it at the threshold.

    The increment is done SQL-side rather than read-modify-write in Python:
    two simultaneous wrong attempts would otherwise both read the same
    counter and write the same value, losing one. Exact counting is not
    security-critical here -- but an attacker able to stay below the
    threshold by firing attempts in parallel would be, and that is what the
    lost update would allow.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        sa.update(User)
        .where(User.id == user.id)
        .values(failed_login_attempts=User.failed_login_attempts + 1)
        .returning(User.failed_login_attempts)
    )
    attempts = result.scalar_one_or_none()
    if attempts is None:  # pragma: no cover - the row was just read
        return

    user.failed_login_attempts = attempts
    if attempts >= MAXIMUM_FAILED_LOGIN_ATTEMPTS and not is_locked(user, now=now):
        locked_until = now + LOCKOUT_DURATION
        await db.execute(
            sa.update(User)
            .where(User.id == user.id)
            .values(locked_until=locked_until, failed_login_attempts=0)
        )
        user.locked_until = locked_until
        # The lock is the penalty for this run of failures, so the run is
        # spent. Left at the threshold, the first wrong password after the
        # lock expired would re-lock for another full duration.
        user.failed_login_attempts = 0
        # Its own audit action, not a second login_failure: "this account was
        # locked" is the event an administrator fielding a support call needs
        # to find, and burying it among the failures that caused it would
        # make them reconstruct it by counting.
        await record_best_effort_audit_event(
            db,
            actor_user_id=None,
            action=AUDIT_ACTION_ACCOUNT_LOCKED,
            entity_type=AUDIT_ENTITY_AUTH,
            entity_id=user.id,
            request=request,
        )


async def _clear_failed_attempts(db: AsyncSession, user: User) -> None:
    """Called on every successful authentication.

    Written unconditionally rather than only when non-zero: the extra UPDATE
    on an already-clean row costs nothing measurable, and a conditional here
    is one more branch that could be wrong about which state it is in.
    """
    await db.execute(
        sa.update(User)
        .where(User.id == user.id)
        .values(failed_login_attempts=0, locked_until=None)
    )
    user.failed_login_attempts = 0
    user.locked_until = None


async def authenticate(
    db: AsyncSession, identifier: str, password: str, *, request: Request | None = None
) -> tuple[User, Role, str, str]:
    user = await user_crud.get_by_identifier(db, identifier)

    # Checked before the password, so attempts against a locked account do
    # not extend the lock. Otherwise an attacker who keeps trying would hold
    # the real user out indefinitely rather than for ten minutes, and the
    # account would never recover while the attack continued.
    if user is not None and is_locked(user):
        await record_best_effort_audit_event(
            db,
            actor_user_id=None,
            action=AUDIT_ACTION_LOGIN_FAILURE,
            entity_type=AUDIT_ENTITY_AUTH,
            entity_id=user.id,
            request=request,
        )
        await commit_best_effort(db)
        minutes = max(1, round(lock_expires_in_seconds(user) / 60))
        raise AccountLockedError(
            f"This account is temporarily locked after "
            f"{MAXIMUM_FAILED_LOGIN_ATTEMPTS} failed sign-in attempts. "
            f"Try again in about {minutes} minute(s)."
        )

    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        # Per ADR-0001: the actor is never the authentication target — a
        # failed login has no authenticated actor, known account or not.
        # A known account may be recorded as the *subject* (entity_id);
        # an unknown submitted identifier is never persisted in any form
        # (not raw, not a deterministic hash, not any other enumerable or
        # correlatable representation) — a low-entropy identifier like an
        # employee code or email remains dictionary-guessable even hashed.
        await record_best_effort_audit_event(
            db,
            actor_user_id=None,
            action=AUDIT_ACTION_LOGIN_FAILURE,
            entity_type=AUDIT_ENTITY_AUTH,
            entity_id=user.id if user is not None else None,
            request=request,
        )
        # An unknown identifier has no account to count against, and
        # inventing somewhere to count it would mean persisting the
        # identifier -- exactly what ADR-0001 forbids. An inactive account
        # is already barred by a stronger rule than this one.
        if user is not None and user.is_active:
            await _record_failed_attempt(db, user, request=request)
        await commit_best_effort(db)
        raise InvalidCredentialsError("Invalid employee code/email or password")

    role_result = await db.get(Role, user.role_id)
    role = role_result
    if role is None:
        raise InvalidCredentialsError("User has no assigned role")

    await _clear_failed_attempts(db, user)
    user.last_login_at = datetime.now(timezone.utc)
    # Best-effort across the whole persistence boundary — both the audit
    # write (record_best_effort_audit_event's own SAVEPOINT) and this
    # commit (commit_best_effort) — must not block a legitimate login. If
    # either fails, last_login_at and/or the audit row may not persist, but
    # token issuance below never depends on this commit succeeding.
    await record_best_effort_audit_event(
        db,
        actor_user_id=user.id,
        action=AUDIT_ACTION_LOGIN_SUCCESS,
        entity_type=AUDIT_ENTITY_AUTH,
        entity_id=user.id,
        request=request,
    )
    # Read everything token issuance needs from the ORM objects *before*
    # commit_best_effort() — a commit-time failure there rolls back the
    # session, which expires every attribute on `user`/`role` and would
    # otherwise turn a legitimate login into a MissingGreenlet 500 the
    # instant those attributes are next touched.
    user_id_str = str(user.id)
    role_name = role.name
    await commit_best_effort(db)

    auth_time = int(datetime.now(timezone.utc).timestamp())  # password login time
    access_token = create_access_token(user_id_str, role_name, auth_time)
    refresh_token = create_refresh_token(user_id_str, auth_time)
    refresh_payload = decode_token(refresh_token)
    await store_refresh_token(
        refresh_payload["jti"], user_id_str, ttl_seconds=settings.JWT_REFRESH_EXPIRE_DAYS * 24 * 3600
    )
    return user, role, access_token, refresh_token


async def refresh_access_token(
    db: AsyncSession, refresh_token: str | None, *, request: Request | None = None
) -> str:
    if not refresh_token:
        raise InvalidRefreshTokenError("Missing refresh token")
    try:
        payload = decode_token(refresh_token)
    except Exception as exc:
        raise InvalidRefreshTokenError("Invalid or expired refresh token") from exc

    if payload.get("type") != "refresh":
        raise InvalidRefreshTokenError("Invalid token type")

    user_id = payload["sub"]
    if not await is_refresh_token_valid(payload["jti"], user_id):
        raise InvalidRefreshTokenError("Refresh token has been revoked")

    try:
        user = await user_crud.get_by_id(db, uuid.UUID(user_id))
    except (ValueError, TypeError) as exc:
        # The "sub" claim is only ever set by this app's own create_refresh_token
        # (see app.core.security), so a malformed value here indicates token
        # corruption rather than user input — treated the same as any other
        # invalid refresh token, not a generic 400.
        raise InvalidRefreshTokenError("Invalid or expired refresh token") from exc
    if user is None or not user.is_active:
        raise InvalidRefreshTokenError("User not found or inactive")

    role = await db.get(Role, user.role_id)
    if role is None:
        raise InvalidRefreshTokenError("User has no assigned role")

    # Best-effort, same rationale as login: preserve current authentication
    # response behavior — an audit-write or commit-time hiccup must not
    # turn a valid refresh into a failure.
    await record_best_effort_audit_event(
        db,
        actor_user_id=user.id,
        action=AUDIT_ACTION_TOKEN_REFRESH,
        entity_type=AUDIT_ENTITY_AUTH,
        entity_id=user.id,
        request=request,
    )
    # See the identical comment in authenticate(): read role.name before
    # commit_best_effort() can roll back and expire it.
    role_name = role.name
    await commit_best_effort(db)

    # auth_time is carried over unchanged: a refresh is not a password login.
    return create_access_token(user_id, role_name, payload.get("auth_time"))


async def logout(db: AsyncSession, refresh_token: str | None, *, request: Request | None = None) -> None:
    if not refresh_token:
        return
    actor_user_id: uuid.UUID | None = None
    try:
        payload = decode_token(refresh_token)
        await revoke_refresh_token(payload["jti"])
        actor_user_id = uuid.UUID(payload["sub"])
    except Exception:
        pass

    # Best-effort, same rationale as login/refresh.
    await record_best_effort_audit_event(
        db,
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_LOGOUT,
        entity_type=AUDIT_ENTITY_AUTH,
        entity_id=actor_user_id,
        request=request,
    )
    await commit_best_effort(db)
