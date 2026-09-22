import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings


user_id = uuid.UUID("a1c60236-f8ed-4402-b018-a13e0ef93f06")

payload = {
    "user_id": str(user_id),
    "role": "CA",
    "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
}

token = jwt.encode(
    payload,
    settings.SECRET_KEY,
    algorithm=settings.ALGORITHM,
)

print(token)