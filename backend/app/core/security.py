import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def _create_token(subject: str, expires_delta: timedelta, token_type: str, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str, role: str) -> str:
    return _create_token(
        user_id,
        timedelta(minutes=settings.JWT_ACCESS_EXPIRE_MINUTES),
        "access",
        extra={"role": role},
    )


def create_refresh_token(user_id: str) -> str:
    return _create_token(user_id, timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS), "refresh")


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
