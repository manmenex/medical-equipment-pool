"""Host-only password reset for one existing user.

Run on the deployment host inside the backend container (never exposed over
HTTP). Recovery path for an Administrator who forgot their password, when no
other Administrator can reset it through the UI.

    python -m app.scripts.reset_password --employee-code ADMIN001

Sets a newly generated temporary password (printed once to stdout, never
logged or stored in plaintext), requires a change at next login, and clears
the login lockout. Audited as PASSWORD_RESET_HOST with no actor
(user_id=None) and never records the password itself.
"""
import argparse
import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.crud import audit as audit_crud
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.scripts.bootstrap_admin import generate_temporary_password


class ResetRefused(RuntimeError):
    """Raised when the reset must not proceed (no such user)."""


async def reset_password(*, employee_code: str) -> tuple[User, str]:
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.employee_code == employee_code).with_for_update())
        ).scalar_one_or_none()
        if user is None:
            raise ResetRefused(f"No user with employee_code={employee_code!r}. Nothing was changed.")

        temp_password = generate_temporary_password(user.employee_code, user.full_name, user.email)
        user.password_hash = hash_password(temp_password)
        user.must_change_password = True
        user.failed_login_attempts = 0
        user.locked_until = None

        await audit_crud.create(
            db,
            user_id=None,
            action="PASSWORD_RESET_HOST",
            entity_type="user",
            entity_id=user.id,
            after_data={"employee_code": user.employee_code, "must_change_password": True},
        )
        await db.commit()
        await db.refresh(user)
        return user, temp_password


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--employee-code", required=True, help="employee code of the user to reset")
    args = parser.parse_args()

    try:
        user, temp_password = await reset_password(employee_code=args.employee_code)
    except ResetRefused as exc:
        print(f"Reset refused: {exc}")
        raise SystemExit(1) from exc

    print("Password reset.")
    print(f"  employee_code: {user.employee_code}")
    print(f"  temporary password (shown once, not stored anywhere else): {temp_password}")
    print("Log in with it now; you will be asked to set a new password.")


if __name__ == "__main__":
    asyncio.run(main())
