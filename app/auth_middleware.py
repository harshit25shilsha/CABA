# from __future__ import annotations

# import uuid

# import jwt
# from fastapi import Request
# from starlette.middleware.base import BaseHTTPMiddleware
# from starlette.responses import JSONResponse

# from app.core.config import settings


# class AuthMiddleware(BaseHTTPMiddleware):
#     """
#     Middleware responsible for:

#     - Reading JWT from the Authorization header
#     - Validating the JWT
#     - Extracting authenticated user information
#     - Storing user information in request.state
#     """

#     PUBLIC_PATHS = {
#         "/health",
#         "/docs",
#         "/redoc",
#         "/openapi.json",
#         f"{settings.API_V1_PREFIX}/openapi.json",
#         "/auth/login",
#     }

#     async def dispatch(self, request: Request, call_next):     
#         if request.url.path in self.PUBLIC_PATHS or request.url.path.startswith("/docs/") or request.url.path.startswith("/redoc/"):
#             return await call_next(request)

        
#         authorization = request.headers.get("Authorization")

#         if not authorization:
#             return JSONResponse(
#                 status_code=401,
#                 content={
#                     "detail": "Authorization header is required"
#                 },
#             )

        
#         if not authorization.startswith("Bearer "):
#             return JSONResponse(
#                 status_code=401,
#                 content={
#                     "detail": "Invalid authorization header"
#                 },
#             )

        
#         token = authorization.replace("Bearer ", "", 1).strip()

#         if not token:
#             return JSONResponse(
#                 status_code=401,
#                 content={
#                     "detail": "Bearer token is required"
#                 },
#             )

#         try:
            
#             payload = jwt.decode(
#                 token,
#                 settings.SECRET_KEY,
#                 algorithms=[settings.ALGORITHM],
#             )

            
#             user_id = payload.get("user_id")
#             role = payload.get("role")

            
#             if not user_id:
#                 return JSONResponse(
#                     status_code=401,
#                     content={
#                         "detail": "user_id is missing from token"
#                     },
#                 )

            
#             try:
#                 user_id = uuid.UUID(str(user_id))
#             except ValueError:
#                 return JSONResponse(
#                     status_code=401,
#                     content={
#                         "detail": "Invalid user_id in token"
#                     },
#                 )

 
#             request.state.user_id = user_id
#             request.state.role = role
#             request.state.jwt_payload = payload

#         except jwt.ExpiredSignatureError:
#             return JSONResponse(
#                 status_code=401,
#                 content={
#                     "detail": "Token has expired"
#                 },
#             )

#         except jwt.InvalidTokenError:
#             return JSONResponse(
#                 status_code=401,
#                 content={
#                     "detail": "Invalid token"
#                 },
#             )

#         return await call_next(request)



from __future__ import annotations
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.core.config import settings
from app.core.security import decode_access_token

class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware responsible for:

    - Reading JWT from the Authorization header
    - Validating the JWT
    - Extracting authenticated user information
    - Storing user information in request.state
    """

    PUBLIC_PATHS = {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        f"{settings.API_V1_PREFIX}/openapi.json",
        "/auth/login",
    }

    async def dispatch(self, request: Request, call_next):     
        if request.url.path in self.PUBLIC_PATHS or request.url.path.startswith("/docs/") or request.url.path.startswith("/redoc/"):
            return await call_next(request)

        authorization = request.headers.get("Authorization")

        if not authorization:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authorization header is required"
                },
            )

        
        if not authorization.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Invalid authorization header"
                },
            )

        
        token = authorization.replace("Bearer ", "", 1).strip()

        if not token:
            return JSONResponse(status_code=401, content={"detail": "Bearer token is required"})

        try:
            
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
            )

            
            user_id = payload.get("user_id")
            role = payload.get("role")

            if not user_id:
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "user_id is missing from token"
                    },
                )

            
            try:
                user_id = uuid.UUID(str(user_id))
            except ValueError:
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "Invalid user_id in token"
                    },
                )

 
            request.state.user_id = user_id
            request.state.role = role
            request.state.jwt_payload = payload

        except jwt.ExpiredSignatureError:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Token has expired"
                },
            )

        except jwt.InvalidTokenError:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Invalid token"
                },
            )

        return await call_next(request)
