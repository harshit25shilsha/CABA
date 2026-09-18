import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.document_request import DocumentRequest


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """CA / Sub-CA / Admin accounts. Clients do not log in as Users in
    Phase 1 — they interact via the upload link tied to a document_request."""

    __tablename__ = "users"

    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True),
        nullable=False,
        default=UserRole.CA,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    clients: Mapped[list["Client"]] = relationship(back_populates="created_by")
    document_requests: Mapped[list["DocumentRequest"]] = relationship(back_populates="created_by")