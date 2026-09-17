"""
One processor class, instantiated once per reasoning task with a
task-specific system prompt — UNDERSTAND_REQUIREMENT, VALIDATE_SEMANTIC,
and GENERATE_EXPLANATION are all GPT-OSS 120B calls that differ only in
prompt and expected output shape, not in how the API is called.

Each task's builder function below returns a ready-to-register instance;
register() all three with AIBrain rather than sharing one instance across
tasks, per the AIProcessor contract (one processor = one task).
"""

import json
import logging

from groq import AsyncGroq, APIConnectionError, APIStatusError, APITimeoutError
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

# Transient failures worth retrying. A malformed response (JSON parse
# failure) is NOT retried here — retrying the same prompt against the
# same model rarely fixes a parsing problem and just burns quota; that
# case surfaces as a failed ProcessorResult instead.
_RETRYABLE_EXCEPTIONS = (APIConnectionError, APITimeoutError, APIStatusError)


UNDERSTAND_REQUIREMENT_PROMPT = """\
You are a document-requirement interpreter for a chartered accountant's \
document intelligence system. Given a CA's freeform requirement text for \
one requested document, output ONLY a JSON object, no other text, with \
this exact shape:
{
  "document_type": string,
  "date_range": {"start": "YYYY-MM-DD" or null, "end": "YYYY-MM-DD" or null} or null,
  "required_fields": [string, ...],
  "constraints": [string, ...],
  "confidence": number between 0 and 1
}
Resolve relative or fiscal-year references into explicit dates (Indian FY \
runs 1 April to 31 March, e.g. "FY 2025-26" = 2025-04-01 to 2026-03-31). \
If something in the requirement is ambiguous, lower confidence and note \
the ambiguity as a string in "constraints" rather than guessing silently.\
"""

VALIDATE_SEMANTIC_PROMPT = """\
You are a semantic validator for a chartered accountant's document \
intelligence system. Given a normalized requirement spec and a document's \
extracted fields, decide whether the document satisfies the requirement. \
Output ONLY a JSON object, no other text, with this exact shape:
{
  "status": "pass" or "fail" or "uncertain",
  "reasoning": string,
  "confidence": number between 0 and 1
}
Use "uncertain" (not a guessed pass/fail) whenever the extracted fields \
don't give you enough to decide confidently.\
"""

GENERATE_EXPLANATION_PROMPT = """\
You write short, plain-language explanations for CAs and their clients \
about why a document was accepted, rejected, or flagged for review. \
Output ONLY a JSON object, no other text, with this exact shape:
{"explanation": string}
Keep it to at most 3 sentences. No jargon, no internal system terms like \
"confidence score" or "embedding" — write for someone who isn't technical.\
"""

CLASSIFY_DOCUMENT_PROMPT = """\
You classify financial/tax documents for a chartered accountant's document \
intelligence system, given the document's extracted text. Output ONLY a \
JSON object, no other text, with this exact shape:
{
  "document_type": string,
  "candidates": [{"document_type": string, "confidence": number between 0 and 1}, ...],
  "confidence": number between 0 and 1
}
"document_type" should be a short lowercase_with_underscores label (e.g. \
"bank_statement", "pan_card", "itr_acknowledgement", "gst_return", \
"invoice"). Don't invent a narrower label than the text supports — if the \
text is genuinely ambiguous between two plausible types, list both in \
"candidates" ordered by confidence and lower the top-level "confidence" \
accordingly rather than picking one arbitrarily. If the text gives no \
usable signal at all, use "document_type": "unknown".\
"""


class GroqReasoningProcessor(AIProcessor):
    def __init__(self, task: ModelTask, system_prompt: str, client: AsyncGroq | None = None):
        self.task = task
        self._system_prompt = system_prompt
        # Injectable client — lets tests supply a fake/mock instead of a
        # real network-bound AsyncGroq instance.
        self._client = client or AsyncGroq(
            api_key=settings.GROQ_API_KEY, timeout=settings.GROQ_TIMEOUT_SECONDS
        )

    async def run(self, context: ProcessingContext) -> ProcessorResult:
        user_content = self._build_user_content(context)
        if user_content is None:
            return ProcessorResult(
                success=False,
                task=self.task,
                model_name=settings.GROQ_MODEL,
                error=f"Missing required input in context for task {self.task.value}",
            )

        try:
            raw_content = await self._call_with_retry(user_content)
        except _RETRYABLE_EXCEPTIONS as exc:
            logger.warning("Groq call failed after retries for task %s: %s", self.task.value, exc)
            return ProcessorResult(
                success=False, task=self.task, model_name=settings.GROQ_MODEL, error=str(exc)
            )

        try:
            parsed = json.loads(raw_content)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Groq returned non-JSON output for task %s: %s", self.task.value, exc)
            return ProcessorResult(
                success=False,
                task=self.task,
                model_name=settings.GROQ_MODEL,
                error=f"Model output was not valid JSON: {exc}",
                output={"raw_content": raw_content},
            )

        return ProcessorResult(
            success=True,
            task=self.task,
            model_name=settings.GROQ_MODEL,
            output=parsed,
            confidence=parsed.get("confidence"),
        )

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(settings.GROQ_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_with_retry(self, user_content: str) -> str:
        response = await self._client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=settings.LLM_TEMPERATURE,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    def _build_user_content(self, context: ProcessingContext) -> str | None:
        if self.task == ModelTask.UNDERSTAND_REQUIREMENT:
            if not context.requirement_text:
                return None
            return f"Requirement text:\n{context.requirement_text}"

        if self.task == ModelTask.VALIDATE_SEMANTIC:
            spec = context.extra.get("normalized_spec")
            if spec is None:
                return None
            fields = context.extra.get("extracted_fields")
            if fields is not None:
                return (
                    f"Requirement spec (JSON):\n{json.dumps(spec)}\n\n"
                    f"Extracted document fields (JSON):\n{json.dumps(fields)}"
                )
            # No structured fields (this came from the plain-text extraction
            # path, not the vision path) — fall back to raw text. GPT-OSS can
            # still reason over it directly; only the deterministic rule
            # engine's field-keyed checks (required_fields_present,
            # client_profile_match) are unavailable on this path, and those
            # already skip gracefully (return None) when extracted_fields
            # isn't present, rather than erroring.
            if context.raw_text:
                return (
                    f"Requirement spec (JSON):\n{json.dumps(spec)}\n\n"
                    f"Extracted document text:\n{context.raw_text}"
                )
            return None

        if self.task == ModelTask.CLASSIFY_DOCUMENT:
            text = context.raw_text
            if not text:
                return None
            return f"Extracted document text:\n{text}"

        if self.task == ModelTask.GENERATE_EXPLANATION:
            decision = context.extra.get("decision_summary")
            if not decision:
                return None
            return f"Decision details (JSON):\n{json.dumps(decision)}"

        return None


def build_requirement_understanding_processor(
    client: AsyncGroq | None = None,
) -> GroqReasoningProcessor:
    return GroqReasoningProcessor(
        ModelTask.UNDERSTAND_REQUIREMENT, UNDERSTAND_REQUIREMENT_PROMPT, client
    )


def build_classification_processor(client: AsyncGroq | None = None) -> GroqReasoningProcessor:
    return GroqReasoningProcessor(ModelTask.CLASSIFY_DOCUMENT, CLASSIFY_DOCUMENT_PROMPT, client)


def build_semantic_validation_processor(client: AsyncGroq | None = None) -> GroqReasoningProcessor:
    return GroqReasoningProcessor(ModelTask.VALIDATE_SEMANTIC, VALIDATE_SEMANTIC_PROMPT, client)


def build_explanation_processor(client: AsyncGroq | None = None) -> GroqReasoningProcessor:
    return GroqReasoningProcessor(
        ModelTask.GENERATE_EXPLANATION, GENERATE_EXPLANATION_PROMPT, client
    )