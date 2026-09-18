import uuid

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole
from app.core.security import decode_access_token


def _bearer_payload(authorization: str | None) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is required")
    try:
        return decode_access_token(token)
    except Exception as exc:  # JWT library exposes several InvalidTokenError subclasses.
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


async def get_authenticated_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = _bearer_payload(authorization)
    raw_user_id = payload.get("user_id")
    if not raw_user_id:
        raise HTTPException(status_code=401, detail="user_id is missing from token")
    try:
        user_id = uuid.UUID(str(raw_user_id))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid user_id in token") from exc

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Authenticated user is inactive or does not exist")
    return user


async def require_ca_or_sub_ca(
    user: User = Depends(get_authenticated_user),
) -> uuid.UUID:
    if user.role not in {UserRole.CA, UserRole.SUB_CA}:
        raise HTTPException(status_code=403, detail="CA or Sub-CA role required")
    return user.id
