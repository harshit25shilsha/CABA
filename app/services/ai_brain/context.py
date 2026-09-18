"""
Data shapes passed into and out of every processor. Deliberately plain
dataclasses, not Pydantic models tied to app/schemas — this package stays
importable and testable without the rest of the app wired up.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.ai_brain.tasks import ModelTask


@dataclass
class ProcessingContext:
    """Everything a processor might need. Individual processors only read
    the fields relevant to them — e.g. a deterministic rule processor
    ignores image_bytes entirely."""

    task: ModelTask
    document_upload_id: uuid.UUID | None = None
    mime_type: str | None = None
    raw_text: str | None = None
    image_bytes: bytes | None = None
    requirement_text: str | None = None
    # Free-form bag for task-specific inputs (e.g. normalized_spec for
    # VALIDATE_SEMANTIC, or the field list for VALIDATE_DETERMINISTIC)
    # instead of growing this dataclass a field at a time per task.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessorResult:
    success: bool
    task: ModelTask
    model_name: str
    output: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    error: str | None = None


class AIBrainError(Exception):
    """Base exception for the ai_brain package."""


class NoProcessorRegisteredError(AIBrainError):
    """Raised when the router is asked to run a task no processor handles.
    This is a configuration bug, not a runtime/data problem — it should
    surface loudly rather than be swallowed into a NEEDS_REVIEW result."""

    def __init__(self, task: ModelTask):
        self.task = task
        super().__init__(f"No processor registered for task: {task.value}")