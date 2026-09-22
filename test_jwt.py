import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from app.core.security import get_user_id_from_token


user_id = uuid.UUID("c506b58f-86de-46f1-b40b-c90b13795edc")

payload = {
    "user_id": str(user_id),
    "role": "CA",
    "exp": datetime.now(timezone.utc) + timedelta(minutes=60),
}

token = jwt.encode(
    payload,
    settings.SECRET_KEY,
    algorithm=settings.ALGORITHM,
)

print("\nJWT:")
print(token)

extracted_user_id = get_user_id_from_token(token)

print("\nOriginal user ID:")
print(user_id)

print("\nExtracted user ID:")
print(extracted_user_id)

print("\nResult:")

if extracted_user_id == user_id:
    print("✅ JWT test passed")
else:
    print("❌ JWT test failed")