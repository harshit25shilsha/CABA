from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.document_upload_ca import (
    router as document_upload_ca_router,
)

from app.core.config import settings
from app.middleware.auth_middleware import AuthMiddleware


app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
)

app.add_middleware(AuthMiddleware)
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Register CA document upload routes
app.include_router(document_upload_ca_router)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/test-auth")
async def test_auth(request: Request):
    user_id = request.state.user_id
    role = request.state.role

    return {
        "message": "Authentication successful",
        "user_id": str(user_id),
        "role": role,
    }

