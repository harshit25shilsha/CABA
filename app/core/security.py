import uuid
import jwt
from app.core.config import settings

def decode_access_token(token: str) -> dict:
    """
    Decode and verify a JWT access token.

    Returns:
        Decoded JWT payload.

    Raises:
        jwt.ExpiredSignatureError: If token has expired.
        jwt.InvalidTokenError: If token is invalid.
    """

    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )

    return payload

def get_user_id_from_token(token: str) -> uuid.UUID:
    """
    Extract user_id from a verified JWT token.
    """

    payload = decode_access_token(token)

    user_id = payload.get("user_id")

    if not user_id:
        raise ValueError("user_id is missing from JWT")

    try:
        return uuid.UUID(str(user_id))
    except ValueError as exc:
        raise ValueError("Invalid user_id in JWT") from exc