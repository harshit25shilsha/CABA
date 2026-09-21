"""
The orchestrator: takes one DocumentUpload and runs it through every AI
Brain stage, writing each result to the DB and landing on a final
VALID/INVALID/NEEDS_REVIEW status. This is the piece that makes the
individually-tested AI Brain processors function as one pipeline.

Deliberately takes file_bytes as a parameter rather than calling a
storage service internally — this stays decoupled from exactly how/where
the bytes were fetched (Cloudinary today, something else later). Whoever
wires the upload API calls the storage service, then passes the bytes in.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AIProcessingResult,
    AuditEvent,
    Client,
    DocumentRequest,
    DocumentUpload,
    RequestedDocument,
    Requirement,
    ValidationResult,
)
from app.models.enums import RequestStatus, RequirementStatus, UploadStatus, ValidationCheckStatus
from app.services.ai_brain import AIBrain, ModelTask, ProcessingContext, resolve_extraction_task

logger = logging.getLogger(__name__)

# Below this confidence on an OCR'd (not native-text) extraction, escalate
# to the vision model for a second pass rather than trusting a low-quality
# OCR read straight into validation.
OCR_ESCALATION_CONFIDENCE_THRESHOLD = 0.6

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass
class PipelineResult:
    upload_id: uuid.UUID
    final_status: UploadStatus
    extraction_model_used: str | None = None
    classification: dict | None = None
    semantic_validation: dict | None = None
    deterministic_checks: list[dict] = field(default_factory=list)
    explanation: str | None = None
    failure_reason: str | None = None


async def process_document_upload(
    upload_id: uuid.UUID,
    file_bytes: bytes,
    db: AsyncSession,
    brain: AIBrain,
) -> PipelineResult:
    upload = await _load_upload(upload_id, db)

    requirement = upload.requested_document.requirement
    client = upload.requested_document.document_request.client

    # --- Stage 0: make sure the requirement has been semantically interpreted ---
    if requirement is not None and requirement.status != RequirementStatus.INTERPRETED:
        await _interpret_requirement(requirement, brain, db)

    normalized_spec = requirement.normalized_spec if requirement else None

    # --- Stage 1: extraction (text-native or visual) ---
    extraction_task = resolve_extraction_task(
        has_native_text_layer=upload.mime_type in ("application/pdf", DOCX_MIME),
        is_scanned_or_image=upload.mime_type.startswith("image/"),
    )
    extraction_result = await brain.run(
        extraction_task,
        ProcessingContext(
            task=extraction_task, mime_type=upload.mime_type, image_bytes=file_bytes
        ),
    )
    await _save_ai_result(db, upload.id, extraction_task, extraction_result)

    if not extraction_result.success:
        return await _finalize(
            db, upload, PipelineResult(
                upload_id=upload.id,
                final_status=UploadStatus.NEEDS_REVIEW,
                failure_reason=f"Extraction failed: {extraction_result.error}",
            ),
        )

    raw_text: str | None = None
    extracted_fields: dict | None = None
    extraction_model_used = extraction_result.model_name

    if extraction_task == ModelTask.EXTRACT_TEXT_NATIVE:
        raw_text = extraction_result.output.get("text")
        used_ocr = extraction_result.output.get("used_ocr", False)

        # Escalate a low-confidence OCR read to the vision model rather
        # than validating against a likely-garbled text extraction.
        if used_ocr and (extraction_result.confidence or 0) < OCR_ESCALATION_CONFIDENCE_THRESHOLD:
            logger.info(
                "Escalating upload %s to EXTRACT_VISUAL — OCR confidence %.2f below threshold",
                upload.id, extraction_result.confidence or 0,
            )
            vision_result = await brain.run(
                ModelTask.EXTRACT_VISUAL,
                ProcessingContext(
                    task=ModelTask.EXTRACT_VISUAL, mime_type=upload.mime_type, image_bytes=file_bytes
                ),
            )
            await _save_ai_result(db, upload.id, ModelTask.EXTRACT_VISUAL, vision_result)
            if vision_result.success:
                extracted_fields = vision_result.output.get("extracted_fields")
                extraction_model_used = vision_result.model_name
                # Keep raw_text as a fallback in case downstream steps want it,
                # but structured fields (once available) take priority below.
    else:  # EXTRACT_VISUAL
        extracted_fields = extraction_result.output.get("extracted_fields")

    # --- Stage 2: classification ---
    classify_input_text = raw_text or json.dumps(
        {"extracted_fields": extracted_fields, "tables": extraction_result.output.get("tables")}
    )
    classify_result = await brain.run(
        ModelTask.CLASSIFY_DOCUMENT,
        ProcessingContext(task=ModelTask.CLASSIFY_DOCUMENT, raw_text=classify_input_text),
    )
    await _save_ai_result(db, upload.id, ModelTask.CLASSIFY_DOCUMENT, classify_result)

    # --- Stage 3a: semantic validation (AI-assisted, judgment calls) ---
    semantic_output: dict | None = None
    if normalized_spec is not None:
        semantic_ctx = ProcessingContext(
            task=ModelTask.VALIDATE_SEMANTIC,
            raw_text=raw_text,
            extra={"normalized_spec": normalized_spec, "extracted_fields": extracted_fields},
        )
        semantic_result = await brain.run(ModelTask.VALIDATE_SEMANTIC, semantic_ctx)
        await _save_ai_result(db, upload.id, ModelTask.VALIDATE_SEMANTIC, semantic_result)
        if semantic_result.success:
            semantic_output = semantic_result.output
            db.add(
                ValidationResult(
                    document_upload_id=upload.id,
                    check_name="semantic_validation",
                    status=ValidationCheckStatus(semantic_output.get("status", "uncertain")),
                    confidence=semantic_result.confidence,
                    evidence={"reasoning": semantic_output.get("reasoning")},
                )
            )

    # --- Stage 3b: deterministic validation (objective, never AI) ---
    deterministic_ctx = ProcessingContext(
        task=ModelTask.VALIDATE_DETERMINISTIC,
        mime_type=upload.mime_type,
        extra={
            "file_size_bytes": upload.file_size_bytes,
            "normalized_spec": normalized_spec,
            "extracted_fields": extracted_fields,
            "client_profile": client.profile_data,
        },
    )
    deterministic_result = await brain.run(ModelTask.VALIDATE_DETERMINISTIC, deterministic_ctx)
    checks = deterministic_result.output["checks"]
    for check in checks:
        db.add(
            ValidationResult(
                document_upload_id=upload.id,
                check_name=check["check_name"],
                expected_value=check["expected_value"],
                actual_value=check["actual_value"],
                status=ValidationCheckStatus(check["status"]),
                evidence={"detail": check["detail"]} if check.get("detail") else None,
            )
        )

    final_status = _combine_final_status(
        deterministic_overall=ValidationCheckStatus(deterministic_result.output["overall_status"]),
        semantic_status=semantic_output.get("status") if semantic_output else None,
    )

    result = PipelineResult(
        upload_id=upload.id,
        final_status=final_status,
        extraction_model_used=extraction_model_used,
        classification=classify_result.output if classify_result.success else None,
        semantic_validation=semantic_output,
        deterministic_checks=checks,
    )

    # --- Stage 4: explanation (client/CA-facing, generated last so it can
    # summarize the actual decision rather than predicting it) ---
    explanation_result = await brain.run(
        ModelTask.GENERATE_EXPLANATION,
        ProcessingContext(
            task=ModelTask.GENERATE_EXPLANATION,
            extra={
                "decision_summary": {
                    "final_status": final_status.value,
                    "deterministic_checks": checks,
                    "semantic_validation": semantic_output,
                }
            },
        ),
    )
    await _save_ai_result(db, upload.id, ModelTask.GENERATE_EXPLANATION, explanation_result)
    if explanation_result.success:
        result.explanation = explanation_result.output.get("explanation")

    return await _finalize(db, upload, result)


async def _load_upload(upload_id: uuid.UUID, db: AsyncSession) -> DocumentUpload:
    stmt = (
        select(DocumentUpload)
        .options(
            selectinload(DocumentUpload.requested_document)
            .selectinload(RequestedDocument.requirement),
            selectinload(DocumentUpload.requested_document)
            .selectinload(RequestedDocument.document_request)
            .selectinload(DocumentRequest.client),
        )
        .where(DocumentUpload.id == upload_id)
    )
    result = await db.execute(stmt)
    upload = result.scalar_one_or_none()
    if upload is None:
        raise ValueError(f"DocumentUpload {upload_id} not found")
    return upload


async def _interpret_requirement(requirement: Requirement, brain: AIBrain, db: AsyncSession) -> None:
    result = await brain.run(
        ModelTask.UNDERSTAND_REQUIREMENT,
        ProcessingContext(task=ModelTask.UNDERSTAND_REQUIREMENT, requirement_text=requirement.raw_text),
    )
    await _save_ai_result(db, None, ModelTask.UNDERSTAND_REQUIREMENT, result, requirement_id=requirement.id)
    if result.success:
        requirement.normalized_spec = result.output
        requirement.status = RequirementStatus.INTERPRETED
    else:
        requirement.status = RequirementStatus.FAILED
    await db.flush()


async def _save_ai_result(
    db: AsyncSession,
    document_upload_id: uuid.UUID | None,
    task: ModelTask,
    result,
    requirement_id: uuid.UUID | None = None,
) -> None:
    # document_upload_id is nullable here because requirement interpretation
    # (Stage 0) runs once per Requirement, not per upload — it has no
    # DocumentUpload to attach to. requirement_id is carried in the output
    # JSON instead of a dedicated FK column, since ai_processing_results was
    # designed around uploads; revisit with a real FK if this needs querying
    # by requirement often.
    output = dict(result.output) if result.success else {"error": result.error}
    if requirement_id is not None:
        output["_requirement_id"] = str(requirement_id)
    if document_upload_id is not None:
        db.add(
            AIProcessingResult(
                document_upload_id=document_upload_id,
                stage=_task_to_stage(task),
                model_name=result.model_name,
                raw_output=output,
                confidence=result.confidence,
            )
        )
        await db.flush()


def _task_to_stage(task: ModelTask):
    from app.models.enums import ProcessingStage

    mapping = {
        ModelTask.CLASSIFY_DOCUMENT: ProcessingStage.CLASSIFICATION,
        ModelTask.EXTRACT_TEXT_NATIVE: ProcessingStage.EXTRACTION,
        ModelTask.EXTRACT_VISUAL: ProcessingStage.EXTRACTION,
        ModelTask.UNDERSTAND_REQUIREMENT: ProcessingStage.REQUIREMENT_UNDERSTANDING,
        ModelTask.VALIDATE_SEMANTIC: ProcessingStage.REQUIREMENT_UNDERSTANDING,
        ModelTask.GENERATE_EXPLANATION: ProcessingStage.REQUIREMENT_UNDERSTANDING,
    }
    return mapping[task]


def _combine_final_status(
    deterministic_overall: ValidationCheckStatus, semantic_status: str | None
) -> UploadStatus:
    if deterministic_overall == ValidationCheckStatus.FAIL:
        return UploadStatus.INVALID
    if semantic_status == "fail":
        return UploadStatus.INVALID
    if semantic_status == "pass" and deterministic_overall != ValidationCheckStatus.FAIL:
        return UploadStatus.VALID
    if deterministic_overall == ValidationCheckStatus.UNCERTAIN:
        return UploadStatus.NEEDS_REVIEW
    if semantic_status in (None, "uncertain"):
        return UploadStatus.NEEDS_REVIEW
    return UploadStatus.VALID


async def _finalize(db: AsyncSession, upload: DocumentUpload, result: PipelineResult) -> PipelineResult:
    upload.status = result.final_status
    db.add(
        AuditEvent(
            entity_type="document_upload",
            entity_id=upload.id,
            event_type="pipeline_completed",
            event_metadata={
                "final_status": result.final_status.value,
                "explanation": result.explanation,
                "failure_reason": result.failure_reason,
            },
        )
    )
    await db.flush()
    await _recompute_request_status(db, upload.requested_document.document_request_id)
    await db.commit()
    return result


async def _recompute_request_status(db: AsyncSession, document_request_id: uuid.UUID) -> None:
    """OPEN -> IN_PROGRESS as soon as any upload has been processed;
    -> COMPLETED once every mandatory requested_document's LATEST upload
    attempt (not just any historical attempt — a later reupload can
    supersede an earlier VALID one) is VALID. A request that regresses
    below that bar (e.g. a reupload invalidates a previously-satisfied
    doc) drops back to IN_PROGRESS rather than staying stuck COMPLETED.
    DRAFT and CANCELLED are left alone — this only manages the
    OPEN/IN_PROGRESS/COMPLETED lifecycle once a request is actually live.
    """
    stmt = (
        select(DocumentRequest)
        .options(
            selectinload(DocumentRequest.requested_documents).selectinload(
                RequestedDocument.uploads
            )
        )
        .where(DocumentRequest.id == document_request_id)
        .with_for_update()
        # Without this, a DocumentRequest/RequestedDocument already sitting
        # in this session's identity map (e.g. this function called twice
        # in one session) would keep its previously-loaded, now-stale
        # `.uploads` collection instead of picking up rows committed since
        # — expire_on_commit=False (db/session.py) means commit() alone
        # doesn't force a reload. populate_existing forces this query's
        # fresh results to overwrite whatever was cached.
        .execution_options(populate_existing=True)
    )
    document_request = (await db.execute(stmt)).scalar_one()

    if document_request.status in (RequestStatus.DRAFT, RequestStatus.CANCELLED):
        return

    mandatory_docs = [rd for rd in document_request.requested_documents if rd.is_mandatory]
    all_mandatory_satisfied = bool(mandatory_docs) and all(
        _latest_upload(rd) is not None and _latest_upload(rd).status == UploadStatus.VALID
        for rd in mandatory_docs
    )

    document_request.status = (
        RequestStatus.COMPLETED if all_mandatory_satisfied else RequestStatus.IN_PROGRESS
    )


def _latest_upload(requested_document: RequestedDocument) -> DocumentUpload | None:
    if not requested_document.uploads:
        return None
    return max(requested_document.uploads, key=lambda u: u.upload_attempt_number)