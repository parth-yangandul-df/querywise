from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.services.embedding_progress import get_all_progress

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.get("/embeddings/status")
async def embedding_status():
    """Return embedding generation progress for all connections."""
    progress = get_all_progress()
    return {
        "tasks": [
            {
                "connection_id": p.connection_id,
                "status": p.status,
                "total": p.total,
                "completed": p.completed,
                "error": p.error,
            }
            for p in progress.values()
        ]
    }


@router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness check — verifies downstream dependencies.

    Not behind authentication — intended for k8s / load balancer health checks.
    """
    checks: dict[str, str] = {}
    info: dict[str, str] = {}

    # Check database connectivity
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {str(exc)[:100]}"
        logger.error("readiness_check: DB unreachable: %s", exc)

    # Informational (not a health check)
    info["llm_provider"] = settings.default_llm_provider

    all_ok = all(v == "ok" for v in checks.values())

    if not all_ok:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": checks, "info": info},
        )

    return {"status": "ready", "checks": checks, "info": info}
