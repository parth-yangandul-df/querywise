from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.base_connector import QueryResult


@pytest.fixture
def mock_db():
    """Mock AsyncSession with add/flush/execute stubs."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mock_query_result():
    """A minimal QueryResult with two rows."""
    return QueryResult(
        columns=["Name", "IsActive"],
        column_types=["nvarchar", "bit"],
        rows=[["Alice", 1], ["Bob", 1]],
        row_count=2,
        execution_time_ms=12.5,
        truncated=False,
    )


@pytest.fixture
def mock_embed_text(monkeypatch):
    """Replace embed_text with a deterministic stub returning a unit vector.

    Patches at the usage site (intent_catalog module) so the already-imported
    reference is replaced correctly.
    """

    async def _stub(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr("app.llm.graph.intent_catalog.embed_text", _stub)
    return _stub
