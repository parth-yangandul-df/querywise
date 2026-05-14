import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.api.v1.schemas.dictionary import (
    DictionaryEntryCreate,
    DictionaryEntryResponse,
    DictionaryEntryUpdate,
)
from app.core.exceptions import NotFoundError
from app.db.models.dictionary import DictionaryEntry
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/columns/{column_id}/dictionary", tags=["dictionary"])


@router.get("", response_model=list[DictionaryEntryResponse])
async def list_dictionary_entries(
    column_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(DictionaryEntry)
        .where(DictionaryEntry.column_id == column_id)
        .order_by(DictionaryEntry.sort_order, DictionaryEntry.raw_value)
    )
    return list(result.scalars().all())


@router.post("", response_model=DictionaryEntryResponse, status_code=201)
async def create_dictionary_entry(
    column_id: uuid.UUID,
    body: DictionaryEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    entry = DictionaryEntry(column_id=column_id, **body.model_dump())
    db.add(entry)
    await db.flush()
    return entry


@router.put("/{entry_id}", response_model=DictionaryEntryResponse)
async def update_dictionary_entry(
    column_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: DictionaryEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    entry = await db.get(DictionaryEntry, entry_id)
    if not entry or entry.column_id != column_id:
        raise NotFoundError("DictionaryEntry", str(entry_id))

    for key, value in body.model_dump(exclude_none=True).items():
        setattr(entry, key, value)

    await db.flush()
    return entry


@router.delete("/{entry_id}", status_code=204)
async def delete_dictionary_entry(
    column_id: uuid.UUID,
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    entry = await db.get(DictionaryEntry, entry_id)
    if not entry or entry.column_id != column_id:
        raise NotFoundError("DictionaryEntry", str(entry_id))
    await db.delete(entry)
    await db.flush()
