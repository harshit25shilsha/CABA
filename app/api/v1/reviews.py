import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.auth_dependencies import require_ca_or_sub_ca
from app.db.session import get_db
from app.models import DocumentUpload, ReviewAction
from app.models.enums import ReviewDecision, UploadStatus
from app.schemas.review import ReviewActionCreate, ReviewActionRead

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("/uploads/{upload_id}", response_model=ReviewActionRead, status_code=201)
async def create_review_action(
    upload_id: uuid.UUID,
    payload: ReviewActionCreate,
    reviewed_by_user_id: uuid.UUID = Depends(require_ca_or_sub_ca),
    db: AsyncSession = Depends(get_db),
) -> ReviewAction:
    upload = (
        await db.execute(
            select(DocumentUpload).where(DocumentUpload.id == upload_id)
        )
    ).scalar_one_or_none()
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    if upload.status not in {UploadStatus.NEEDS_REVIEW, UploadStatus.VALID, UploadStatus.INVALID}:
        raise HTTPException(
            status_code=409,
            detail=f"This upload cannot be reviewed in its current status: {upload.status.value}",
        )

    review = ReviewAction(
        document_upload_id=upload_id,
        reviewed_by_user_id=reviewed_by_user_id,
        decision=payload.decision,
        notes=payload.notes,
    )
    db.add(review)

    if payload.decision == ReviewDecision.APPROVED:
        upload.status = UploadStatus.VALID
    elif payload.decision == ReviewDecision.REJECTED:
        upload.status = UploadStatus.INVALID
    elif payload.decision == ReviewDecision.REQUEST_REUPLOAD:
        upload.status = UploadStatus.NEEDS_REVIEW

    await db.commit()
    await db.refresh(review)
    return review


@router.get("/uploads", response_model=list[ReviewActionRead])
async def list_review_actions(
    status: UploadStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[ReviewAction]:
    stmt = select(ReviewAction).options(selectinload(ReviewAction.document_upload))
    if status is not None:
        stmt = stmt.where(ReviewAction.document_upload.has(DocumentUpload.status == status))
    stmt = stmt.order_by(ReviewAction.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


@router.get("/uploads/needing-review", response_model=list[dict])
async def list_needing_review_uploads(
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(DocumentUpload)
        .options(selectinload(DocumentUpload.requested_document))
        .where(DocumentUpload.status == UploadStatus.NEEDS_REVIEW)
        .order_by(DocumentUpload.updated_at.desc())
    )
    uploads = (await db.execute(stmt)).scalars().all()

    result = []
    for upload in uploads:
        result.append(
            {
                "upload_id": str(upload.id),
                "request_id": str(upload.requested_document.document_request_id),
                "requested_document_id": str(upload.requested_document_id),
                "client_id": str(upload.client_id),
                "original_filename": upload.original_filename,
                "status": upload.status.value,
                "created_at": upload.created_at,
                "updated_at": upload.updated_at,
            }
        )
    return result
