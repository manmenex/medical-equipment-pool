import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import (
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


class InvalidCredentialsError(DomainError):
    code = "INVALID_CREDENTIALS"
    status_code = 401


class InvalidRefreshTokenError(DomainError):
    code = "INVALID_REFRESH_TOKEN"
    status_code = 401


class WeakPasswordError(DomainError):
    code = "WEAK_PASSWORD"
    status_code = 400


class SamePasswordError(DomainError):
    code = "SAME_PASSWORD"
    status_code = 400


# Length, not composition. A 12-character passphrase a ward nurse can
# actually remember is stronger in practice than an 8-character
# "P@ssw0rd!" that gets written on a sticky note next to the workstation,
# and NIST SP 800-63B has recommended exactly this trade for years. The
# only other rule is that the new password must differ from the current
# one, which stops "change" from meaning "retype".
MINIMUM_PASSWORD_LENGTH = 12


def validate_new_password(new_password: str) -> None:
    """Raises WeakPasswordError if the password is unacceptable.

    Separate from change_password so the rule has one home and can be
    tested directly, rather than being re-expressed at every call site.
    """
    if new_password is None or len(new_password) < MINIMUM_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"New password must be at least {MINIMUM_PASSWORD_LENGTH} characters long."
        )
    if new_password.strip() != new_password:
        # Leading/trailing whitespace is almost always an accident of
        # copy-paste, and an account whose password depends on an invisible
        # character is one nobody can support over the phone.
        raise WeakPasswordError("New password must not start or end with whitespace.")


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
    if not verify_password(current_password, user.password_hash):
        await record_best_effort_audit_event(
            db,
            actor_user_id=user.id,
            action=AUDIT_ACTION_LOGIN_FAILURE,
            entity_type=AUDIT_ENTITY_AUTH,
            entity_id=user.id,
            request=request,
        )
        await commit_best_effort(db)
        # Deliberately the same error the login path raises: "wrong current
        # password" and "wrong password" are the same fact about the same
        # secret, and inventing a second code would say more, not less.
        raise InvalidCredentialsError("Current password is incorrect")

    validate_new_password(new_password)

    if verify_password(new_password, user.password_hash):
        raise SamePasswordError("New password must be different from the current password.")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False

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


async def authenticate(
    db: AsyncSession, identifier: str, password: str, *, request: Request | None = None
) -> tuple[User, Role, str, str]:
    user = await user_crud.get_by_identifier(db, identifier)
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
        await commit_best_effort(db)
        raise InvalidCredentialsError("Invalid employee code/email or password")

    role_result = await db.get(Role, user.role_id)
    role = role_result
    if role is None:
        raise InvalidCredentialsError("User has no assigned role")

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

    access_token = create_access_token(user_id_str, role_name)
    refresh_token = create_refresh_token(user_id_str)
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

    return create_access_token(user_id, role_name)


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
