import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user, require_role
from app.api.v1.schemas.metric import MetricCreate, MetricResponse, MetricUpdate
from app.core.exceptions import NotFoundError
from app.db.models.metric import MetricDefinition
from app.db.models.user import User
from app.db.session import get_db
from app.services.embedding_service import embed_metric

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])


@router.get(
    "/connections/{connection_id}/metrics",
    response_model=list[MetricResponse],
)
async def list_metrics(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    result = await db.execute(
        select(MetricDefinition)
        .where(MetricDefinition.connection_id == connection_id)
        .order_by(MetricDefinition.display_name)
    )
    return list(result.scalars().all())


@router.post(
    "/connections/{connection_id}/metrics",
    response_model=MetricResponse,
    status_code=201,
)
async def create_metric(
    connection_id: uuid.UUID,
    body: MetricCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    metric = MetricDefinition(
        connection_id=connection_id,
        **body.model_dump(),
    )
    db.add(metric)
    await db.flush()
    try:
        metric.metric_embedding = await embed_metric(metric)
    except Exception:
        logger.warning("Failed to embed metric %s", metric.id, exc_info=True)
    await db.flush()
    await db.refresh(metric)
    return metric


@router.get(
    "/connections/{connection_id}/metrics/{metric_id}",
    response_model=MetricResponse,
)
async def get_metric(
    connection_id: uuid.UUID,
    metric_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    metric = await db.get(MetricDefinition, metric_id)
    if not metric or metric.connection_id != connection_id:
        raise NotFoundError("Metric", str(metric_id))
    return metric


@router.put(
    "/connections/{connection_id}/metrics/{metric_id}",
    response_model=MetricResponse,
)
async def update_metric(
    connection_id: uuid.UUID,
    metric_id: uuid.UUID,
    body: MetricUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    metric = await db.get(MetricDefinition, metric_id)
    if not metric or metric.connection_id != connection_id:
        raise NotFoundError("Metric", str(metric_id))

    for key, value in body.model_dump(exclude_none=True).items():
        setattr(metric, key, value)

    await db.flush()
    try:
        metric.metric_embedding = await embed_metric(metric)
    except Exception:
        logger.warning("Failed to embed metric %s", metric_id, exc_info=True)
    await db.flush()
    await db.refresh(metric)
    return metric


@router.delete(
    "/connections/{connection_id}/metrics/{metric_id}",
    status_code=204,
)
async def delete_metric(
    connection_id: uuid.UUID,
    metric_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    metric = await db.get(MetricDefinition, metric_id)
    if not metric or metric.connection_id != connection_id:
        raise NotFoundError("Metric", str(metric_id))
    await db.delete(metric)
    await db.flush()
