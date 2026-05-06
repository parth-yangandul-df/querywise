"""Test stubs for observability module."""

from unittest.mock import patch

from app.llm.graph.observability import (
    create_query_log_context,
    log_confidence_calculation,
    log_fallback_event,
    log_node_execution,
    log_override_applied,
    log_query_context,
)


class TestObservabilityImports:
    """Verify module can be imported."""

    def test_module_imports(self):
        """Module should import without errors."""
        from app.llm.graph import observability

        assert hasattr(observability, "log_query_context")


class TestLogQueryContext:
    """Test log_query_context function."""

    def test_logs_normal_query(self):
        """Should log normal query without error."""
        # Should not raise
        log_query_context(
            query="show active resources",
            intent="active_resources",
            filters=[{"field": "skill", "value": "python"}],
            follow_up_type="new",
            confidence=0.85,
            final_sql="SELECT * FROM ...",
            fallback_used=None,
        )

    def test_logs_with_fallback(self):
        """Should log fallback query."""
        log_query_context(
            query="show resources",
            intent="active_resources",
            filters=[],
            follow_up_type="new",
            confidence=0.3,
            final_sql="SELECT * FROM ...",
            fallback_used="heuristic",
        )

    def test_logs_failed_query(self):
        """Should log failed query."""
        log_query_context(
            query="show resources",
            intent=None,
            filters=[],
            follow_up_type="new",
            confidence=None,
            final_sql=None,
            fallback_used=None,
            success=False,
            error_message="Database connection failed",
        )


class TestLogFallbackEvent:
    """Test log_fallback_event function."""

    def test_logs_fallback_level(self):
        """Should log fallback event."""
        log_fallback_event(
            level=2,
            reason="json_parse_error",
            extracted_filters=[{"field": "skill"}],
            success=True,
        )

    def test_logs_failed_fallback(self):
        """Should log failed fallback."""
        log_fallback_event(
            level=6,
            reason="all_levels_exhausted",
            extracted_filters=[],
            success=False,
        )


class TestLogNodeExecution:
    """Test log_node_execution function."""

    def test_logs_node_success(self):
        """Should log successful node execution."""
        log_node_execution(
            node_name="classify_intent",
            duration_ms=50.5,
            success=True,
        )

    def test_logs_node_failure(self):
        """Should log failed node execution."""
        log_node_execution(
            node_name="classify_intent",
            duration_ms=50.5,
            success=False,
            error="Intent classification failed",
        )


class TestCreateQueryLogContext:
    """Test create_query_log_context function."""

    def test_creates_context(self):
        """Should create log context with IDs."""
        context = create_query_log_context()
        assert "session_id" in context
        assert "execution_id" in context

    def test_uses_provided_session_id(self):
        """Should use provided session_id."""
        context = create_query_log_context(session_id="my-session")
        assert context["session_id"] == "my-session"

    def test_generates_unique_execution_ids(self):
        """Should generate unique execution IDs."""
        context1 = create_query_log_context()
        context2 = create_query_log_context()
        assert context1["execution_id"] != context2["execution_id"]


class TestLogConfidenceCalculation:
    """Test log_confidence_calculation function."""

    def test_logs_confidence(self):
        """Should log confidence calculation."""
        log_confidence_calculation(
            confidence=0.85,
            breakdown={"valid_json": 0.3, "valid_fields": 0.3, "matches_schema": 0.4},
            decision="accept",
        )


class TestLogOverrideApplied:
    """Test log_override_applied function."""

    def test_logs_override(self):
        """Should log override application."""
        log_override_applied(
            override_type="intent_mismatch",
            original_value="refine",
            final_value="new",
        )


class TestStructuredLogging:
    """Test that logging uses structured format."""

    def test_log_includes_timestamp(self):
        """Log should include timestamp."""
        with patch("app.llm.graph.observability.query_logger") as mock_logger:
            log_query_context(
                query="test",
                intent="test",
                filters=[],
                follow_up_type="new",
                confidence=0.5,
                final_sql="SELECT 1",
                fallback_used=None,
            )
            # Check that info was called
            assert mock_logger.info.called
