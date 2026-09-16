from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.document_upload_ca import (
    router as document_upload_ca_router,
)

from app.core.config import settings


app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
)


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