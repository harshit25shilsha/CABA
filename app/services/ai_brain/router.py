"""
The AI Brain: a thin dispatch layer with no model logic of its own. It
holds a {ModelTask: AIProcessor} registry and routes a task to whichever
processor is registered for it. Swapping GPT-OSS for another model, or
adding a second vision model for a new document type, means changing
what gets registered — never changing this file.
"""

import logging

from app.services.ai_brain.context import (
    NoProcessorRegisteredError,
    ProcessingContext,
    ProcessorResult,
)
from app.services.ai_brain.processors.base import AIProcessor
from app.services.ai_brain.tasks import ModelTask

logger = logging.getLogger(__name__)


class AIBrain:
    def __init__(self, processors: list[AIProcessor] | None = None):
        self._registry: dict[ModelTask, AIProcessor] = {}
        for processor in processors or []:
            self.register(processor)

    def register(self, processor: AIProcessor) -> None:
        if processor.task in self._registry:
            logger.warning(
                "Overwriting existing processor for task %s (%s -> %s)",
                processor.task.value,
                type(self._registry[processor.task]).__name__,
                type(processor).__name__,
            )
        self._registry[processor.task] = processor

    def is_registered(self, task: ModelTask) -> bool:
        return task in self._registry

    async def run(self, task: ModelTask, context: ProcessingContext) -> ProcessorResult:
        """Route `context` to the processor registered for `task`.

        Raises NoProcessorRegisteredError if nothing is registered for the
        task — a missing registration is a startup/config bug, so it fails
        loudly here rather than quietly returning a NEEDS_REVIEW-shaped
        result that would be indistinguishable from a genuine model failure.
        """
        processor = self._registry.get(task)
        if processor is None:
            raise NoProcessorRegisteredError(task)

        if context.task != task:
            logger.warning(
                "Context.task (%s) does not match requested task (%s) — "
                "using the requested task for routing.",
                context.task.value,
                task.value,
            )

        return await processor.run(context)