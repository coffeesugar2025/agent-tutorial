import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _encode(sub: str, token_type: str, expires: timedelta, extra: dict | None = None) -> tuple[str, str]:
    jti = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "type": token_type,
        "jti": jti,
        "iat": now,
        "exp": now + expires,
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti


def create_access_token(sub: str, extra: dict | None = None) -> tuple[str, str]:
    return _encode(
        sub, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), extra
    )


def create_refresh_token(sub: str) -> tuple[str, str]:
    return _encode(sub, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def access_token_ttl() -> int:
    return settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
