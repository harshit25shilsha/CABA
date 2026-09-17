"""
The interface every processor implements — Tesseract, Qwen, GPT-OSS 120B,
and the deterministic rule engine are all just implementations of this.
The router only ever talks to this interface, never to a concrete
processor's own methods — that's what makes swapping models later a
config/registration change instead of a router-code change.
"""

from abc import ABC, abstractmethod

from app.services.ai_brain.context import ProcessingContext, ProcessorResult
from app.services.ai_brain.tasks import ModelTask


class AIProcessor(ABC):
    """Subclass this for every concrete processor (TesseractProcessor,
    QwenVisionProcessor, GroqReasoningProcessor, DeterministicRuleProcessor, ...)."""

    #: The task this processor handles. A processor handles exactly one
    #: task — a "reasoning" processor that does both UNDERSTAND_REQUIREMENT
    #: and VALIDATE_SEMANTIC is registered twice under two instances (or a
    #: shared internal client), never matched by loose duck-typing here.
    
    task: ModelTask

    @abstractmethod
    async def run(self, context: ProcessingContext) -> ProcessorResult:
        """Execute this processor's work and return a result. Implementations
        must catch their own model/API-specific exceptions and return a
        ProcessorResult(success=False, error=...) rather than raising —
        raising should be reserved for router-level configuration errors."""
        
        raise NotImplementedError