"""
Import every model module here. Alembic's env.py imports this package
(not individual model files) so `Base.metadata` always reflects the full
schema, and so relationship() string references like Mapped["Client"]
resolve correctly regardless of which module happens to be imported first.

When you add a new model file, add its import here too.
"""

from app.db.base import Base
from app.models.ai_result import AIProcessingResult, ValidationResult
from app.models.client import Client
from app.models.document_request import (
    DocumentRequest,
    Requirement,
    RequestedDocument,
)
from app.models.review import AuditEvent, ReviewAction
from app.models.service import Service, SubService
from app.models.upload import Document, DocumentUpload
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "Client",
    "Service",
    "SubService",
    "DocumentRequest",
    "RequestedDocument",
    "Requirement",
    "DocumentUpload",
    "Document",
    "AIProcessingResult",
    "ValidationResult",
    "ReviewAction",
    "AuditEvent",
]