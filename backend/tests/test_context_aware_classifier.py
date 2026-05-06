"""Tests for context-aware classify_intent: _is_refinement_followup() and fast path."""

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LAST_TURN = {
    "intent": "benched_resources",
    "domain": "resource",
    "params": {"skill": "Python"},
    "columns": ["employeeid", "ResourceName", "EmailId", "TechCategoryName"],
    "sql": "SELECT DISTINCT r.employeeid FROM resources r WHERE r.IsActive = 0",
}


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
        "conversation_history": [],
        "last_turn_context": None,
        "user_role": None,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Unit tests for _is_refinement_followup (state-based, no async needed)
# ---------------------------------------------------------------------------


def test_is_refinement_followup_short_question_with_context():
    """Short question (≤3 content words) + context with SQL → True."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    # "know python" → 2 content words after stop word removal
    assert _is_refinement_followup("know python", _LAST_TURN) is True


def test_is_refinement_followup_which_one_of_these_know_python():
    """'Which one of these know python?' — previously broken, now True (short after stops)."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    # "which", "one", "of", "these" are all stop words; "know", "python" = 2 content words
    assert _is_refinement_followup("Which one of these know python?", _LAST_TURN) is True


def test_is_refinement_followup_which_of_these_know_python():
    """Original phrase 'Which of these know Python?' still works."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    assert _is_refinement_followup("Which of these know Python?", _LAST_TURN) is True


def test_is_refinement_followup_filter_by_active():
    """'Filter by active only' → short question → True."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    # "filter", "active", "only" = 3 content words (≤3) → True
    assert _is_refinement_followup("Filter by active only", _LAST_TURN) is True


def test_is_refinement_followup_among_them():
    """'Among them who are assigned?' → short content words → True."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    # stop words: among, them, who, are; content: "assigned" = 1 word → True
    assert _is_refinement_followup("Among them, who are assigned?", _LAST_TURN) is True


def test_is_refinement_followup_only_inactive():
    """'only those who are inactive' → short → True."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    # stop words: only, those, who, are; content: "inactive" = 1 word → True
    assert _is_refinement_followup("only those who are inactive", _LAST_TURN) is True


def test_is_refinement_followup_column_overlap():
    """Question with ≥30% content-word overlap with prior column names → True."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    # content words: ["resourcename", "employeeid", "benched", "staff"] = 4 total
    # overlap: "resourcename" + "employeeid" both in _LAST_TURN["columns"] → 2/4 = 50% ≥ 30%
    assert (
        _is_refinement_followup("show resourcename and employeeid for benched staff", _LAST_TURN)
        is True
    )


def test_is_refinement_followup_returns_false_no_context():
    """'Which of these know Python?' + None → False (no last_turn_context)."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    assert _is_refinement_followup("Which of these know Python?", None) is False


def test_is_refinement_followup_returns_false_no_sql():
    """last_turn_context present but sql is empty → False."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    no_sql_context = {**_LAST_TURN, "sql": ""}
    assert _is_refinement_followup("know python", no_sql_context) is False


def test_is_refinement_followup_returns_false_long_no_overlap():
    """Long fresh question with no overlap → False."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    # Many content words, none matching prior columns/params
    assert (
        _is_refinement_followup(
            "Show all active frontend engineers working on mobile applications", _LAST_TURN
        )
        is False
    )


def test_is_refinement_followup_returns_false_no_sql_key():
    """last_turn_context with no 'sql' key at all → False."""
    from app.llm.graph.nodes.intent_classifier import _is_refinement_followup

    no_sql_key = {"intent": "benched_resources", "domain": "resource", "params": {}, "columns": []}
    assert _is_refinement_followup("know python", no_sql_key) is False


# ---------------------------------------------------------------------------
# classify_intent fast path tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_intent_followup_inherits_prior():
    """classify_intent with deictic follow-up returns inherited intent/domain/0.95."""
    from app.llm.graph.nodes.intent_classifier import classify_intent

    state = _base_state(
        question="Which of these know Python?",
        last_turn_context=_LAST_TURN,
    )

    with (
        patch("app.llm.graph.nodes.intent_classifier.embed_text", AsyncMock()) as mock_embed,
        patch("app.llm.graph.nodes.intent_classifier.ensure_catalog_embedded", AsyncMock()),
    ):
        result = await classify_intent(state)

    # embed_text must NOT be called — this is the fast path
    mock_embed.assert_not_called()

    assert result["domain"] == "resource"
    assert result["intent"] == "benched_resources"
    assert result["confidence"] == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_classify_intent_followup_rbac_gate():
    """user_role='user' with resource domain context → confidence=0.0 (RBAC blocked)."""
    from app.llm.graph.nodes.intent_classifier import classify_intent

    state = _base_state(
        question="Which of these know Python?",
        last_turn_context=_LAST_TURN,  # domain="resource"
        user_role="user",
    )

    with (
        patch("app.llm.graph.nodes.intent_classifier.embed_text", AsyncMock()) as mock_embed,
        patch("app.llm.graph.nodes.intent_classifier.ensure_catalog_embedded", AsyncMock()),
    ):
        result = await classify_intent(state)

    mock_embed.assert_not_called()  # fast path still, not embedding

    assert result["confidence"] == pytest.approx(0.0)
    assert result["domain"] is None
    assert result["intent"] is None


@pytest.mark.asyncio
async def test_classify_intent_followup_user_self_domain_passes_rbac():
    """user_role='user' with user_self domain context → allowed (confidence=0.95)."""
    from app.llm.graph.nodes.intent_classifier import classify_intent

    user_self_context = {**_LAST_TURN, "domain": "user_self", "intent": "my_projects"}
    state = _base_state(
        question="Which of these know Python?",
        last_turn_context=user_self_context,
        user_role="user",
    )

    with (
        patch("app.llm.graph.nodes.intent_classifier.embed_text", AsyncMock()) as mock_embed,
        patch("app.llm.graph.nodes.intent_classifier.ensure_catalog_embedded", AsyncMock()),
    ):
        result = await classify_intent(state)

    mock_embed.assert_not_called()
    assert result["confidence"] == pytest.approx(0.95)
    assert result["domain"] == "user_self"


@pytest.mark.asyncio
async def test_classify_intent_normal_path_unchanged():
    """Fresh long question with no prior overlap goes through embedding (no fast path)."""
    from app.llm.graph.nodes.intent_classifier import classify_intent

    from app.llm.graph.intent_catalog import INTENT_CATALOG

    # Patch catalog so first entry gets matching embedding
    first_entry = INTENT_CATALOG[0]
    identical_embedding = [1.0, 0.0, 0.0]
    first_entry.embedding = identical_embedding

    state = _base_state(
        question="List project managers with more than five years of experience",  # no short-path trigger
        last_turn_context=_LAST_TURN,  # context present but irrelevant for fresh questions
    )

    with (
        patch(
            "app.llm.graph.nodes.intent_classifier.embed_text",
            AsyncMock(return_value=identical_embedding),
        ) as mock_embed,
        patch("app.llm.graph.nodes.intent_classifier.ensure_catalog_embedded", AsyncMock()),
        patch(
            "app.llm.graph.nodes.intent_classifier.get_catalog_embeddings",
            return_value=[[1.0, 0.0, 0.0]] + [[0.0, 1.0, 0.0]] * (len(INTENT_CATALOG) - 1),
        ),
    ):
        result = await classify_intent(state)

    # embed_text MUST be called — fresh question takes normal path
    mock_embed.assert_called_once()

    assert result["confidence"] == pytest.approx(1.0, abs=1e-6)
    assert result["domain"] == first_entry.domain
    assert result["intent"] == first_entry.name
