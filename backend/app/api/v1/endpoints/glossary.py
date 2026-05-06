import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user, require_role
from app.api.v1.schemas.glossary import (
    GlossaryTermCreate,
    GlossaryTermResponse,
    GlossaryTermUpdate,
)
from app.core.exceptions import NotFoundError
from app.db.models.glossary import GlossaryTerm
from app.db.models.user import User
from app.db.session import get_db
from app.services.embedding_service import embed_glossary_term

logger = logging.getLogger(__name__)

router = APIRouter(tags=["glossary"])


@router.get(
    "/connections/{connection_id}/glossary",
    response_model=list[GlossaryTermResponse],
)
async def list_glossary_terms(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    result = await db.execute(
        select(GlossaryTerm)
        .where(GlossaryTerm.connection_id == connection_id)
        .order_by(GlossaryTerm.term)
    )
    return list(result.scalars().all())


@router.post(
    "/connections/{connection_id}/glossary",
    response_model=GlossaryTermResponse,
    status_code=201,
)
async def create_glossary_term(
    connection_id: uuid.UUID,
    body: GlossaryTermCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    term = GlossaryTerm(
        connection_id=connection_id,
        term=body.term,
        definition=body.definition,
        sql_expression=body.sql_expression,
        related_tables=body.related_tables,
        related_columns=body.related_columns,
        examples=body.examples,
    )
    db.add(term)
    await db.flush()
    try:
        term.term_embedding = await embed_glossary_term(term)
    except Exception:
        logger.warning("Failed to embed glossary term %s", term.id, exc_info=True)
    await db.flush()
    await db.refresh(term)
    return term


@router.get(
    "/connections/{connection_id}/glossary/{term_id}",
    response_model=GlossaryTermResponse,
)
async def get_glossary_term(
    connection_id: uuid.UUID,
    term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    term = await db.get(GlossaryTerm, term_id)
    if not term or term.connection_id != connection_id:
        raise NotFoundError("GlossaryTerm", str(term_id))
    return term


@router.put(
    "/connections/{connection_id}/glossary/{term_id}",
    response_model=GlossaryTermResponse,
)
async def update_glossary_term(
    connection_id: uuid.UUID,
    term_id: uuid.UUID,
    body: GlossaryTermUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    term = await db.get(GlossaryTerm, term_id)
    if not term or term.connection_id != connection_id:
        raise NotFoundError("GlossaryTerm", str(term_id))

    for key, value in body.model_dump(exclude_none=True).items():
        setattr(term, key, value)

    await db.flush()
    try:
        term.term_embedding = await embed_glossary_term(term)
    except Exception:
        logger.warning("Failed to embed glossary term %s", term_id, exc_info=True)
    await db.flush()
    await db.refresh(term)
    return term


@router.delete(
    "/connections/{connection_id}/glossary/{term_id}",
    status_code=204,
)
async def delete_glossary_term(
    connection_id: uuid.UUID,
    term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    term = await db.get(GlossaryTerm, term_id)
    if not term or term.connection_id != connection_id:
        raise NotFoundError("GlossaryTerm", str(term_id))
    await db.delete(term)
    await db.flush()
