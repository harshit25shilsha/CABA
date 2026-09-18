import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models import Client, DocumentRequest, RequestedDocument, Requirement
from app.models.enums import RequestStatus, RequirementStatus
from app.schemas.document_request import DocumentRequestCreate, DocumentRequestRead

router = APIRouter(prefix="/requests", tags=["requests"])


@router.post("", response_model=DocumentRequestRead, status_code=201)
async def create_document_request(
    payload: DocumentRequestCreate, db: AsyncSession = Depends(get_db)
) -> DocumentRequest:
    client = (
        await db.execute(select(Client).where(Client.id == payload.client_id))
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    if not payload.requested_documents:
        raise HTTPException(
            status_code=422, detail="A request must include at least one requested document"
        )

    request = DocumentRequest(
        client_id=payload.client_id,
        created_by_user_id=payload.created_by_user_id,
        description=payload.description,
        status=RequestStatus.OPEN,
    )
    db.add(request)
    await db.flush()  # need request.id for the child rows below

    for item in payload.requested_documents:
        requested_doc = RequestedDocument(
            document_request_id=request.id,
            document_type=item.document_type,
            is_mandatory=item.is_mandatory,
            display_order=item.display_order,
        )
        db.add(requested_doc)
        await db.flush()  # need requested_doc.id for its Requirement

        db.add(
            Requirement(
                requested_document_id=requested_doc.id,
                raw_text=item.requirement_text,
                status=RequirementStatus.PENDING_INTERPRETATION,
            )
        )

    await db.commit()

    # Re-fetch with everything loaded so the response has the full nested
    # shape (requested_documents + their requirements) in one round trip.
    return await _load_request(request.id, db)


@router.get("/{request_id}", response_model=DocumentRequestRead)
async def get_document_request(
    request_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> DocumentRequest:
    request = await _load_request(request_id, db)
    if request is None:
        raise HTTPException(status_code=404, detail="Document request not found")
    return request


async def _load_request(request_id: uuid.UUID, db: AsyncSession) -> DocumentRequest | None:
    stmt = (
        select(DocumentRequest)
        .options(
            selectinload(DocumentRequest.requested_documents).selectinload(
                RequestedDocument.requirement
            )
        )
        .where(DocumentRequest.id == request_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()
