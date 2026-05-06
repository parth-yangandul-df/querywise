from unittest.mock import AsyncMock, patch

import pytest

from app.llm.graph.intent_catalog import INTENT_CATALOG


def _base_state(**overrides):
    state = {
        "question": "show active resources",
        "connection_id": "00000000-0000-0000-0000-000000000001",
        "connector_type": "sqlserver",
        "connection_string": "dsn=test",
        "timeout_seconds": 30,
        "max_rows": 100,
        "db": None,
        "domain": None,
        "intent": None,
        "confidence": 0.0,
        "params": {},
        "sql": None,
        "result": None,
        "generated_sql": None,
        "retry_count": 0,
        "explanation": None,
        "llm_provider": None,
        "llm_model": None,
        "answer": None,
        "highlights": [],
        "suggested_followups": [],
        "execution_id": None,
        "execution_time_ms": None,
        "error": None,
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_classify_intent_high_confidence():
    """When question embedding matches first catalog entry exactly, confidence=1.0."""
    from app.llm.graph.nodes.intent_classifier import classify_intent

    first_entry = INTENT_CATALOG[0]
    identical_embedding = [1.0, 0.0, 0.0]
    first_entry.embedding = identical_embedding

    with (
        patch(
            "app.llm.graph.nodes.intent_classifier.embed_text",
            AsyncMock(return_value=identical_embedding),
        ),
        patch("app.llm.graph.nodes.intent_classifier.ensure_catalog_embedded", AsyncMock()),
        patch(
            "app.llm.graph.nodes.intent_classifier.get_catalog_embeddings",
            return_value=[[1.0, 0.0, 0.0]] + [[0.0, 1.0, 0.0]] * 23,
        ),
    ):
        state = _base_state()
        updates = await classify_intent(state)

    assert updates["confidence"] == pytest.approx(1.0, abs=1e-6)
    assert updates["domain"] == first_entry.domain
    assert updates["intent"] == first_entry.name


@pytest.mark.asyncio
async def test_classify_intent_low_confidence_orthogonal():
    """Orthogonal embedding → confidence~0 (below threshold)."""
    from app.llm.graph.nodes.intent_classifier import classify_intent

    with (
        patch(
            "app.llm.graph.nodes.intent_classifier.embed_text",
            AsyncMock(return_value=[0.0, 0.0, 1.0]),
        ),
        patch("app.llm.graph.nodes.intent_classifier.ensure_catalog_embedded", AsyncMock()),
        patch(
            "app.llm.graph.nodes.intent_classifier.get_catalog_embeddings",
            return_value=[[1.0, 0.0, 0.0]] * 24,
        ),
    ):
        state = _base_state()
        updates = await classify_intent(state)

    assert updates["confidence"] == pytest.approx(0.0, abs=1e-6)


def test_route_after_classify_high_confidence():
    from app.llm.graph.nodes.intent_classifier import route_after_classify

    state = _base_state(confidence=0.95, domain="resource", intent="active_resources")
    assert route_after_classify(state) == "extract_params"


def test_route_after_classify_low_confidence():
    from app.llm.graph.nodes.intent_classifier import route_after_classify

    state = _base_state(confidence=0.50, domain="resource", intent="active_resources")
    assert route_after_classify(state) == "llm_fallback"


def test_route_after_classify_at_threshold():
    """Confidence exactly at threshold routes to extract_params."""
    from app.llm.graph.nodes.intent_classifier import _THRESHOLD, route_after_classify

    state = _base_state(confidence=_THRESHOLD, domain="resource", intent="active_resources")
    assert route_after_classify(state) == "extract_params"


# ── Person Name Detection Tests ───────────────────────────────────────────────


def test_has_person_name_two_capitalized_words():
    """Two consecutive capitalized words trigger person name detection."""
    from app.llm.graph.nodes.classifier_keywords import _has_person_name

    assert _has_person_name("Show Gautham R M project assignments")
    assert _has_person_name("John Smith works on Python")
    assert _has_person_name("What are Jane Doe's skills?")
    assert _has_person_name("Tell me about Alice Johnson")
    assert _has_person_name("Mary Ann joined last week")


def test_has_person_name_single_capitalized_word():
    """Single capitalized word (like "Python" or "SQL") does NOT trigger."""
    from app.llm.graph.nodes.classifier_keywords import _has_person_name

    assert not _has_person_name("Show me my Python projects")
    assert not _has_person_name("What is my SQL timesheet")
    assert not _has_person_name("My project assignments")


def test_has_person_name_no_names():
    """Questions without person names return False."""
    from app.llm.graph.nodes.classifier_keywords import _has_person_name

    assert not _has_person_name("show active resources")
    assert not _has_person_name("what are benched developers")
    assert not _has_person_name("list all projects")


# ── Keyword Route Person Name Guard Tests ─────────────────────────────────────


def test_keyword_route_person_name_skips_user_self():
    """Queries about named people skip _USER_SELF_KEYWORDS even with 'my'/'me'."""
    from app.llm.graph.nodes.intent_classifier import _keyword_route

    # "Show me Gautham R M project assignments" — "me" is followed by a name
    result = _keyword_route("Show me Gautham R M project assignments")
    # Should NOT return my_projects/user_self — let embedding decide
    assert result is None or result[0] != "my_projects"

    # Same for "my" with a person name
    result = _keyword_route("my John Smith timesheets")
    assert result is None or result[0] != "my_projects"


def test_keyword_route_genuine_user_self_still_works():
    """Genuine 'my projects' queries (no person name) still route correctly."""
    from app.llm.graph.nodes.intent_classifier import _keyword_route

    result = _keyword_route("show my projects")
    assert result == ("my_projects", "user_self")

    result = _keyword_route("my timesheets")
    assert result == ("my_projects", "user_self")

    result = _keyword_route("show my timesheet")
    assert result == ("my_projects", "user_self")
