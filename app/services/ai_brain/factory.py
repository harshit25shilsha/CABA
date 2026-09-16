"""
Builds the application's AIBrain with every processor registered — this
is the one place that knows the full current lineup — routes/services
should get their AIBrain from here, never construct processors or the
router directly. All 7 ModelTask values have a registered processor as
of this version.
"""

from functools import lru_cache

from app.services.ai_brain.processors.groq_processor import (
    build_classification_processor,
    build_explanation_processor,
    build_requirement_understanding_processor,
    build_semantic_validation_processor,
)

from app.services.ai_brain.processors.gemini_vision_processor import GeminiVisionProcessor
from app.services.ai_brain.processors.rule_engine import DeterministicRuleProcessor

from app.services.ai_brain.processors.tesseract_processor import TesseractProcessor
from app.services.ai_brain.router import AIBrain


def build_ai_brain() -> AIBrain:
    """Construct a fresh AIBrain. Prefer get_ai_brain() (below) in normal
    app code — this is exposed separately for tests that want an isolated
    instance rather than the process-wide singleton."""
    return AIBrain(
        [
            TesseractProcessor(),
            GeminiVisionProcessor(),
            build_classification_processor(),
            build_requirement_understanding_processor(),
            build_semantic_validation_processor(),
            build_explanation_processor(),
            DeterministicRuleProcessor(),
        ]
    )




@lru_cache
def get_ai_brain() -> AIBrain:
    """FastAPI dependency / process-wide singleton. Processors hold their
    own API clients (e.g. AsyncGroq) which should be constructed once and
    reused across requests, not rebuilt per call.
 
    Usage:
        @router.post("/requests/{id}/interpret")
        async def interpret(brain: AIBrain = Depends(get_ai_brain)):
            ...
    """
    return build_ai_brain()