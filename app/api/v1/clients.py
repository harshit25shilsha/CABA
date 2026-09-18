import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth_dependencies import require_ca_or_sub_ca
from app.db.session import get_db
from app.models import Client
from app.schemas.client import ClientCreate, ClientRead

router = APIRouter(prefix="/clients", tags=["clients"])


@router.post("", response_model=ClientRead, status_code=201)
async def create_client(
    payload: ClientCreate,
    created_by_user_id: uuid.UUID = Depends(require_ca_or_sub_ca),
    db: AsyncSession = Depends(get_db),
) -> Client:
    client = Client(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        pan_number=payload.pan_number,
        created_by_user_id=created_by_user_id,
        profile_data=payload.profile_data,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientRead)
async def get_client(client_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Client:
    client = (await db.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client
