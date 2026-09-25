"""
Alembic's env.py imports this package so `Base.metadata` contains every
database table owned by the Java-integration AI Brain service. Add new model
imports here whenever the service gains another persisted entity.
"""

from app.db.base import Base
from app.models.external_validation import ExternalValidationJob

__all__ = [
    "Base",
    "ExternalValidationJob",
]
