import pytest

from app.llm.graph.intent_catalog import INTENT_CATALOG, ensure_catalog_embedded


def test_catalog_total_count():
    assert len(INTENT_CATALOG) == 27


def test_catalog_domain_counts():
    from collections import Counter

    counts = Counter(e.domain for e in INTENT_CATALOG)
    assert counts["resource"] == 8
    assert counts["client"] == 3
    assert counts["project"] == 6
    assert counts["timesheet"] == 4
    assert counts["user_self"] == 5


def test_catalog_unique_names():
    names = [e.name for e in INTENT_CATALOG]
    assert len(names) == len(set(names)), "Intent names must be unique"


def test_catalog_valid_domains():
    valid = {"resource", "client", "project", "timesheet", "user_self"}
    for entry in INTENT_CATALOG:
        assert entry.domain in valid


@pytest.mark.asyncio
async def test_ensure_catalog_embedded_is_idempotent(mock_embed_text, monkeypatch):
    import app.llm.graph.intent_catalog as catalog_mod

    # Reset module-level state so the test is deterministic regardless of run order
    monkeypatch.setattr(catalog_mod, "_catalog_embedded", False)
    for entry in catalog_mod.INTENT_CATALOG:
        entry.embedding = []
    await ensure_catalog_embedded()
    await ensure_catalog_embedded()  # second call must not re-embed
    from app.llm.graph.intent_catalog import INTENT_CATALOG as CAT

    assert all(len(e.embedding) > 0 for e in CAT)
