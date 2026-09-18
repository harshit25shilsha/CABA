from fastapi import APIRouter

from app.api.v1 import clients, requests, uploads


api_router = APIRouter()

api_router.include_router(clients.router)
api_router.include_router(requests.router)
api_router.include_router(uploads.router)