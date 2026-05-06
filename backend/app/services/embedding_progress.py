"""In-memory progress tracker for background embedding generation."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class EmbeddingProgress:
    connection_id: str
    total: int = 0
    completed: int = 0
    status: str = "pending"  # pending | running | completed | failed
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_progress: dict[str, EmbeddingProgress] = {}
_tasks: dict[str, asyncio.Task] = {}
_get_call_count: int = 0  # counter for periodic stale cleanup


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------

_STALE_THRESHOLD_HOURS = 1


def _is_stale(progress: EmbeddingProgress) -> bool:
    """Return True if a completed/failed entry is older than the stale threshold."""
    if progress.finished_at is None:
        return False
    age = (datetime.now(UTC) - progress.finished_at).total_seconds()
    return age > _STALE_THRESHOLD_HOURS * 3600


def _cleanup_stale_entries() -> None:
    """Remove progress entries that completed or failed over an hour ago."""
    stale_ids = [cid for cid, p in _progress.items() if _is_stale(p)]
    for cid in stale_ids:
        _progress.pop(cid, None)
        _tasks.pop(cid, None)


def cleanup_progress(connection_id: str) -> None:
    """Remove progress and task entries for a specific connection."""
    _progress.pop(connection_id, None)
    _tasks.pop(connection_id, None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_tracking(connection_id: str, total: int) -> EmbeddingProgress:
    p = EmbeddingProgress(
        connection_id=connection_id,
        total=total,
        status="running",
        started_at=datetime.now(UTC),
    )
    _progress[connection_id] = p
    return p


def increment(connection_id: str) -> None:
    if connection_id not in _progress:
        return
    p = _progress[connection_id]
    p.completed += 1
    if p.total > 0 and p.completed >= p.total:
        mark_completed(connection_id)


def mark_completed(connection_id: str) -> None:
    if connection_id in _progress:
        p = _progress[connection_id]
        p.status = "completed"
        p.finished_at = datetime.now(UTC)


def mark_failed(connection_id: str, error: str) -> None:
    if connection_id in _progress:
        p = _progress[connection_id]
        p.status = "failed"
        p.error = error
        p.finished_at = datetime.now(UTC)


def get_progress(connection_id: str) -> EmbeddingProgress | None:
    global _get_call_count
    _get_call_count += 1
    if _get_call_count % 20 == 0:
        _cleanup_stale_entries()
    return _progress.get(connection_id)


def get_all_progress() -> dict[str, EmbeddingProgress]:
    return dict(_progress)


def register_task(connection_id: str, task: asyncio.Task) -> None:
    """Store task reference to prevent garbage collection."""
    _tasks[connection_id] = task


def is_running(connection_id: str) -> bool:
    return connection_id in _progress and _progress[connection_id].status == "running"
