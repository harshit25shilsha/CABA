"""AI validation pipeline for documents owned by the Java application."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.models.enums import ValidationCheckStatus, ValidationVerdict
from app.models.external_validation import ExternalValidationJob
from app.services.ai_brain import AIBrain, ModelTask, ProcessingContext, resolve_extraction_task

logger = logging.getLogger(__name__)

OCR_ESCALATION_CONFIDENCE_THRESHOLD = 0.6
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass
class ExternalPipelineResult:
    verdict: ValidationVerdict
    confidence: float | None = None
    explanation: str | None = None
    checks: list[dict] = field(default_factory=list)
    failure_reason: str | None = None


async def process_external_validation(
    job: ExternalValidationJob,
    file_bytes: bytes,
    file_size_bytes: int,
    brain: AIBrain,
) -> ExternalPipelineResult:
    """Run the reusable AI Brain stages against Java's direct job inputs."""

    requirement_result = await brain.run(
        ModelTask.UNDERSTAND_REQUIREMENT,
        ProcessingContext(task=ModelTask.UNDERSTAND_REQUIREMENT, requirement_text=job.requirement_text),
    )
    normalized_spec = requirement_result.output if requirement_result.success else None

    extraction_task = resolve_extraction_task(
        has_native_text_layer=job.mime_type in ("application/pdf", DOCX_MIME),
        is_scanned_or_image=job.mime_type.startswith("image/"),
    )
    extraction_result = await brain.run(
        extraction_task,
        ProcessingContext(
            task=extraction_task,
            mime_type=job.mime_type,
            image_bytes=file_bytes,
        ),
    )
    if not extraction_result.success:
        return ExternalPipelineResult(
            verdict=ValidationVerdict.NEEDS_REVIEW,
            confidence=extraction_result.confidence,
            explanation="The document could not be read reliably and needs manual review.",
            checks=[
                {
                    "name": "document_extraction",
                    "status": ValidationCheckStatus.UNCERTAIN.value,
                    "passed": False,
                    "detail": extraction_result.error,
                }
            ],
            failure_reason=f"Extraction failed: {extraction_result.error}",
        )

    raw_text: str | None = None
    extracted_fields: dict | None = None
    extraction_confidence = extraction_result.confidence
    if extraction_task == ModelTask.EXTRACT_TEXT_NATIVE:
        raw_text = extraction_result.output.get("text")
        if extraction_result.output.get("used_ocr", False) and (extraction_confidence or 0) < OCR_ESCALATION_CONFIDENCE_THRESHOLD:
            vision_result = await brain.run(
                ModelTask.EXTRACT_VISUAL,
                ProcessingContext(
                    task=ModelTask.EXTRACT_VISUAL,
                    mime_type=job.mime_type,
                    image_bytes=file_bytes,
                ),
            )
            if vision_result.success:
                extracted_fields = vision_result.output.get("extracted_fields")
                extraction_confidence = vision_result.confidence
            else:
                logger.warning("Vision escalation failed for Java validation %s: %s", job.upload_id, vision_result.error)
    else:
        extracted_fields = extraction_result.output.get("extracted_fields")

    classify_input = raw_text or json.dumps(
        {"extracted_fields": extracted_fields, "tables": extraction_result.output.get("tables")}
    )
    await brain.run(
        ModelTask.CLASSIFY_DOCUMENT,
        ProcessingContext(task=ModelTask.CLASSIFY_DOCUMENT, raw_text=classify_input),
    )

    semantic_output: dict | None = None
    semantic_confidence: float | None = None
    if normalized_spec is not None:
        semantic_result = await brain.run(
            ModelTask.VALIDATE_SEMANTIC,
            ProcessingContext(
                task=ModelTask.VALIDATE_SEMANTIC,
                raw_text=raw_text,
                extra={"normalized_spec": normalized_spec, "extracted_fields": extracted_fields},
            ),
        )
        if semantic_result.success:
            semantic_output = semantic_result.output
            semantic_confidence = semantic_result.confidence

    deterministic_result = await brain.run(
        ModelTask.VALIDATE_DETERMINISTIC,
        ProcessingContext(
            task=ModelTask.VALIDATE_DETERMINISTIC,
            mime_type=job.mime_type,
            extra={
                "file_size_bytes": file_size_bytes,
                "normalized_spec": normalized_spec,
                "extracted_fields": extracted_fields,
                "client_profile": job.client_profile,
            },
        ),
    )
    checks = [_webhook_check(check) for check in deterministic_result.output["checks"]]
    semantic_status = semantic_output.get("status") if semantic_output else None
    if semantic_output is not None:
        checks.append(
            {
                "name": "semantic_validation",
                "status": semantic_status,
                "passed": semantic_status == ValidationCheckStatus.PASS.value,
                "confidence": semantic_confidence,
                "detail": semantic_output.get("reasoning"),
            }
        )
    elif normalized_spec is None:
        checks.append(
            {
                "name": "requirement_interpretation",
                "status": ValidationCheckStatus.UNCERTAIN.value,
                "passed": False,
                "detail": requirement_result.error,
            }
        )

    verdict = _combine_verdict(
        ValidationCheckStatus(deterministic_result.output["overall_status"]), semantic_status
    )
    explanation_result = await brain.run(
        ModelTask.GENERATE_EXPLANATION,
        ProcessingContext(
            task=ModelTask.GENERATE_EXPLANATION,
            extra={
                "decision_summary": {
                    "final_status": verdict.value,
                    "deterministic_checks": checks,
                    "semantic_validation": semantic_output,
                }
            },
        ),
    )
    explanation = explanation_result.output.get("explanation") if explanation_result.success else _default_explanation(verdict)
    return ExternalPipelineResult(
        verdict=verdict,
        confidence=semantic_confidence if semantic_confidence is not None else extraction_confidence,
        explanation=explanation,
        checks=checks,
    )


def _combine_verdict(
    deterministic_overall: ValidationCheckStatus, semantic_status: str | None
) -> ValidationVerdict:
    if deterministic_overall == ValidationCheckStatus.FAIL or semantic_status == "fail":
        return ValidationVerdict.INVALID
    if deterministic_overall == ValidationCheckStatus.UNCERTAIN:
        return ValidationVerdict.NEEDS_REVIEW
    if semantic_status in (None, "uncertain"):
        return ValidationVerdict.NEEDS_REVIEW
    return ValidationVerdict.VALID


def _webhook_check(check: dict) -> dict:
    status = str(check.get("status") or "").lower()
    return {
        "name": check["check_name"],
        "status": check.get("status"),
        "passed": status == ValidationCheckStatus.PASS.value,
        "expected_value": check.get("expected_value"),
        "actual_value": check.get("actual_value"),
        "detail": check.get("detail"),
    }


def _default_explanation(verdict: ValidationVerdict) -> str:
    if verdict == ValidationVerdict.VALID:
        return "The document meets the requested criteria."
    if verdict == ValidationVerdict.INVALID:
        return "The document does not meet the requested criteria."
    return "The document needs manual review because it could not be verified with confidence."
