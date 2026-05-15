"""self_critique node — LLM self-checks SQL before validation.

Catches hallucinations and schema mismatches early by asking the LLM
to critique its own generated SQL against the provided context.
"""

import logging
from typing import Any

from app.config import settings
from app.core.metrics import timed_node
from app.llm.base_provider import LLMConfig, LLMMessage
from app.llm.graph.state import GraphState
from app.llm.provider_registry import get_provider
from app.llm.utils import repair_json
import json

logger = logging.getLogger(__name__)


_SELF_CRITIQUE_SYSTEM_PROMPT = """You are a SQL validation assistant.

Given a SQL query and the database schema context it was generated from, check:
1. Are all table names in the SQL present in the context?
2. Are all column names in the SQL present in the context?
3. Are there any obvious syntax errors?

Respond with a JSON object:
{
  "valid": true/false,
  "issues": ["list of specific issues found"],
  "confidence": 0.0-1.0
}

Be strict — if a column or table is not clearly in the context, mark it as an issue."""


@timed_node("self_critique")
async def self_critique(state: GraphState) -> dict[str, Any]:
    """Have the LLM critique its own SQL before validation.

    This catches hallucinations early, before expensive validation cycles.
    """
    generated_sql = state.get("generated_sql")
    prompt_context = state.get("prompt_context") or ""

    if not generated_sql:
        logger.debug("self_critique: no SQL to critique")
        return {"critique_valid": True, "critique_issues": []}

    # Use cheap model for critique
    provider = get_provider(settings.default_llm_provider)
    config = LLMConfig(
        model=settings.resolver_model,  # Fast/cheap model
        temperature=0.0,
        max_tokens=512,
    )

    user_prompt = f"""Context (truncated):
{prompt_context[:3000]}

Generated SQL:
{generated_sql}

Check for hallucinated tables/columns."""

    try:
        response = await provider.complete(
            [
                LLMMessage(role="system", content=_SELF_CRITIQUE_SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_prompt),
            ],
            config,
        )

        # Track token usage and cost in MLflow
        from app.core.mlflow_tracing import set_mlflow_llm_cost

        set_mlflow_llm_cost(
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            provider=provider.provider_type.value,
        )

        parsed = json.loads(repair_json(response.content))
        is_valid = parsed.get("valid", True)
        issues = parsed.get("issues", [])
        confidence = parsed.get("confidence", 0.5)

        if not is_valid and issues:
            logger.info(
                "self_critique: issues detected confidence=%.2f issues=%r",
                confidence,
                issues[:3],
            )
            return {
                "critique_valid": False,
                "critique_issues": issues,
                # Pass issues to validation for potential context rebuild
                "validation_issues": issues,
            }

        logger.debug("self_critique: SQL passed self-check")
        return {"critique_valid": True, "critique_issues": []}

    except Exception as e:
        logger.warning("self_critique: failed - %s", e, exc_info=True)
        # Fail open — let validation handle it
        return {"critique_valid": True, "critique_issues": []}


def route_after_critique(state: GraphState) -> str:
    """Route to validation (if passed) or handle_error (if issues found)."""
    if not state.get("critique_valid", True):
        logger.info("route_after_critique: issues found, routing to handle_error")
        return "handle_error"
    return "validate_sql"
