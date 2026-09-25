"""API v1 route registry for the Java integration service."""

from fastapi import APIRouter

from app.api.v1 import validations

api_router = APIRouter()
api_router.include_router(validations.router)
