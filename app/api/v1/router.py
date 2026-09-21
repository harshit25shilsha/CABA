from fastapi import APIRouter

from app.api.v1 import clients, request_attachments, requests, uploads

api_router = APIRouter()
api_router.include_router(clients.router)
api_router.include_router(requests.router)
api_router.include_router(request_attachments.router)
api_router.include_router(uploads.router)
