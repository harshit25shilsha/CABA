import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.dependencies import require_ca_or_sub_ca,get_current_user
from app.db.session import get_db
from app.models import Client, DocumentRequest, RequestedDocument, Requirement, Service, SubService
from app.models.enums import RequestStatus, RequirementStatus
from app.schemas.document_request import DocumentRequestCreate, DocumentRequestRead
from app.api.v1.dependencies import require_ca_or_sub_ca

router = APIRouter(prefix="/requests", tags=["requests"])

# @router.get("/test-auth")
# async def test_auth(
#     current_user: dict = Depends(get_current_user),
# ):
#     return {
#         "message": "Authentication successful",
#         "user_id": str(current_user["user_id"]),
#         "role": current_user["role"],
#     }

@router.get("", response_model=list[DocumentRequestRead])
async def list_document_requests(
    # created_by_user_id: uuid.UUID = Depends(require_ca_or_sub_ca),
    current_user: dict = Depends(require_ca_or_sub_ca),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRequest]:
    created_by_user_id = current_user["user_id"]
    stmt = (
        select(DocumentRequest)
        .options(
            selectinload(DocumentRequest.requested_documents).selectinload(RequestedDocument.requirement),
            selectinload(DocumentRequest.attachments),
        )
        .where(DocumentRequest.created_by_user_id == created_by_user_id)
        .order_by(DocumentRequest.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("", response_model=DocumentRequestRead, status_code=201)
async def create_document_request(
    payload: DocumentRequestCreate,
    # created_by_user_id: uuid.UUID = Depends(require_ca_or_sub_ca),
    current_user: dict = Depends(require_ca_or_sub_ca),
    db: AsyncSession = Depends(get_db),
) -> DocumentRequest:
    created_by_user_id = current_user["user_id"]
    client = (await db.execute(select(Client).where(Client.id == payload.client_id))).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    if not payload.requested_documents:
        raise HTTPException(status_code=422, detail="A request must include at least one requested document")

    if payload.service_id is not None:
        service = (await db.execute(select(Service).where(Service.id == payload.service_id))).scalar_one_or_none()
        if service is None:
            raise HTTPException(status_code=404, detail="Service not found")

    if payload.sub_service_id is not None:
        sub_service = (await db.execute(select(SubService).where(SubService.id == payload.sub_service_id))).scalar_one_or_none()
        if sub_service is None:
            raise HTTPException(status_code=404, detail="Sub-service not found")
        if payload.service_id is None or sub_service.service_id != payload.service_id:
            raise HTTPException(status_code=422, detail="Sub-service must belong to the selected service")

    document_request = DocumentRequest(
        client_id=payload.client_id,
        created_by_user_id=created_by_user_id,
        service_id=payload.service_id,
        sub_service_id=payload.sub_service_id,
        description=payload.description,
        status=RequestStatus.DRAFT,
    )
    db.add(document_request)
    await db.flush()

    for item in payload.requested_documents:
        requested_doc = RequestedDocument(
            document_request_id=document_request.id,
            document_type=item.document_type,
            is_mandatory=item.is_mandatory,
            display_order=item.display_order,
        )
        db.add(requested_doc)
        await db.flush()
        db.add(Requirement(
            requested_document_id=requested_doc.id,
            raw_text=item.requirement_text,
            status=RequirementStatus.PENDING_INTERPRETATION,
        ))

    await db.commit()
    return await _load_request(document_request.id, db)


@router.get("/{request_id}", response_model=DocumentRequestRead)
async def get_document_request(
    request_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> DocumentRequest:
    document_request = await _load_request(request_id, db)
    if document_request is None:
        raise HTTPException(status_code=404, detail="Document request not found")
    return document_request


@router.post("/{request_id}/publish", response_model=DocumentRequestRead)
async def publish_document_request(
    request_id: uuid.UUID,
    _caller_id: uuid.UUID = Depends(require_ca_or_sub_ca),
    db: AsyncSession = Depends(get_db),
) -> DocumentRequest:
    """Moves a request from DRAFT to OPEN — the client upload endpoint
    refuses uploads against a request that hasn't been published, so this
    is the step that actually makes a request client-facing."""
    document_request = (
        await db.execute(select(DocumentRequest).where(DocumentRequest.id == request_id))
    ).scalar_one_or_none()
    if document_request is None:
        raise HTTPException(status_code=404, detail="Document request not found")
    if document_request.status != RequestStatus.DRAFT:
        raise HTTPException(
            status_code=409,
            detail=f"Only a DRAFT request can be published (current status: {document_request.status.value})",
        )
    document_request.status = RequestStatus.OPEN
    await db.commit()
    return await _load_request(request_id, db)


async def _load_request(request_id: uuid.UUID, db: AsyncSession) -> DocumentRequest | None:
    stmt = (
        select(DocumentRequest)
        .options(
            selectinload(DocumentRequest.requested_documents).selectinload(RequestedDocument.requirement),
            selectinload(DocumentRequest.attachments),
        )
        .where(DocumentRequest.id == request_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()