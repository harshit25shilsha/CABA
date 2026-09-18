"""
Handles ModelTask.EXTRACT_VISUAL — visual document understanding for
scanned documents, forms, layout-heavy pages, and tables. Currently wired
to Google Gemini 2.5 Flash on the free API tier (Phase 1 dev), via
Gemini's OpenAI-compatible endpoint.

This is deliberately NOT basic OCR (see TesseractProcessor for that):
the model is asked to understand structure — key-value fields, table
rows, layout regions — not just transcribe characters off the page.

Provider swap: change VISION_API_KEY/VISION_MODEL/VISION_BASE_URL in
.env, and register a different processor class for EXTRACT_VISUAL in
factory.py. Nothing in AIBrain, AIProcessor, or the router changes —
that boundary is the whole point of the router design.
"""

import base64
import json
import logging

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.services.ai_brain.context import ProcessingContext, ProcessorResult
from app.services.ai_brain.processors.base import AIProcessor
from app.services.ai_brain.tasks import ModelTask

logger = logging.getLogger(__name__)

_RETRYABLE_EXCEPTIONS = (APIConnectionError, APITimeoutError, APIStatusError)

VISION_SYSTEM_PROMPT = """\
You extract structured information from scanned financial/tax documents, \
forms, and tables — images where layout and visual structure carry \
meaning, not just plain text. Output ONLY a JSON object, no other text, \
with this exact shape:
{
  "extracted_fields": {<key>: <value>, ...},
  "tables": [{"headers": [string, ...], "rows": [[string, ...], ...]}, ...],
  "layout_notes": [string, ...],
  "confidence": number between 0 and 1
}
Use lowercase_with_underscores keys in "extracted_fields" (e.g. \
"account_number", "pan_number", "statement_date"). If the image quality \
makes a field genuinely unreadable, omit that field rather than guessing, \
and note the issue in "layout_notes", lowering "confidence" accordingly.\
"""


class GeminiVisionProcessor(AIProcessor):
    task = ModelTask.EXTRACT_VISUAL

    def __init__(self, client: AsyncOpenAI | None = None):
        # Injectable client — lets tests supply a fake instead of a real
        # network-bound AsyncOpenAI instance.
        self._client = client or AsyncOpenAI(
            api_key=settings.VISION_API_KEY,
            base_url=settings.VISION_BASE_URL,
            timeout=settings.VISION_TIMEOUT_SECONDS,
        )

    async def run(self, context: ProcessingContext) -> ProcessorResult:
        if not context.image_bytes:
            return ProcessorResult(
                success=False,
                task=self.task,
                model_name=settings.VISION_MODEL,
                error="No image bytes provided in context.image_bytes",
            )

        mime = context.mime_type or "image/png"
        data_url = f"data:{mime};base64,{base64.b64encode(context.image_bytes).decode()}"

        try:
            raw_content = await self._call_with_retry(data_url)
        except _RETRYABLE_EXCEPTIONS as exc:
            logger.warning("Vision model call failed after retries: %s", exc)
            return ProcessorResult(
                success=False, task=self.task, model_name=settings.VISION_MODEL, error=str(exc)
            )

        try:
            parsed = json.loads(raw_content)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Vision model returned non-JSON output: %s", exc)
            return ProcessorResult(
                success=False,
                task=self.task,
                model_name=settings.VISION_MODEL,
                error=f"Model output was not valid JSON: {exc}",
                output={"raw_content": raw_content},
            )

        return ProcessorResult(
            success=True,
            task=self.task,
            model_name=settings.VISION_MODEL,
            output=parsed,
            confidence=parsed.get("confidence"),
        )

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(settings.VISION_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_with_retry(self, data_url: str) -> str:
        response = await self._client.chat.completions.create(
            model=settings.VISION_MODEL,
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract the structured fields, tables, and layout notes from this document image.",
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            temperature=settings.LLM_TEMPERATURE,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content