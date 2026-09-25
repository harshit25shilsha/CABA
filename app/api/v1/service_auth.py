"""Authentication for requests sent by the Java backend."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def require_java_service_key(authorization: str | None = Header(default=None)) -> None:
    if not settings.AI_BRAIN_SERVICE_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Java integration authentication is not configured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service credentials")

    supplied_key = authorization[7:].strip()
    if not supplied_key or not secrets.compare_digest(supplied_key, settings.AI_BRAIN_SERVICE_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service credentials")
