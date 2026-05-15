"""Agent: Query Composer — converts NL questions to SQL."""

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

from app.llm.base_provider import BaseLLMProvider, LLMConfig, LLMMessage
from app.llm.prompts.composer_prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.llm.tracing import traceable
from app.llm.utils import repair_json


@dataclass
class ComposerOutput:
    generated_sql: str
    explanation: str
    confidence: float
    tables_used: list[str]
    assumptions: list[str]


class QueryComposerAgent:
    def __init__(self, provider: BaseLLMProvider, config: LLMConfig):
        self.provider = provider
        self.config = config

    @traceable(name="agent.compose_sql")
    async def compose(
        self,
        question: str,
        assembled_context: str,
        conversation_history: list[dict] | None = None,
    ) -> ComposerOutput:
        """Generate SQL from natural language using provided context.

        Args:
            question: The current user question.
            assembled_context: Semantic context (schema, glossary, etc.).
            conversation_history: Optional prior turns as [{role, content}, ...].
                Injected as additional context before the current question so the
                LLM can resolve pronouns and follow-up references.
        """
        user_prompt = USER_PROMPT_TEMPLATE.format(
            context=assembled_context,
            question=question,
        )

        messages: list[LLMMessage] = [LLMMessage(role="system", content=SYSTEM_PROMPT)]

        # Prepend prior conversation turns so the LLM has follow-up context
        if conversation_history:
            for turn in conversation_history:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append(LLMMessage(role=role, content=content))

        messages.append(LLMMessage(role="user", content=user_prompt))

        response = await self.provider.complete(messages, self.config)

        # Track token usage and cost in MLflow (OpenRouter models like
        # deepseek/qwen aren't in litellm's pricing catalog, so we use
        # the actual cost from OpenRouter's usage.cost response field).
        from app.core.mlflow_tracing import set_mlflow_llm_cost

        set_mlflow_llm_cost(
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            provider=self.provider.provider_type.value,
        )

        # Parse JSON response (repair handles common Ollama/local model issues)
        raw_content = response.content

        # Strip chain-of-thought reasoning tags (used by qwen3, deepseek-r1, etc.)
        # These consume output tokens and can cause truncation before SQL is generated.
        # The actual SQL is always AFTER the </think> tag.
        if raw_content and "<think>" in raw_content:
            think_end = raw_content.find("</think>")
            if think_end != -1:
                raw_content = raw_content[think_end + len("</think>"):].strip()
            else:
                # Unclosed <think> tag — response was truncated during reasoning
                logger.error(
                    "compose: LLM response truncated during reasoning (unclosed <think> tag) — "
                    "model spent all output tokens on chain-of-thought. Asking user to simplify."
                )
                return ComposerOutput(
                    generated_sql="",
                    explanation="Model spent output budget on reasoning. Please simplify.",
                    confidence=0.0,
                    tables_used=[],
                    assumptions=[],
                )

        # Detect truncated responses (mid-reasoning) — fail fast instead of infinite retry
        if response.finish_reason == "length" or raw_content.rstrip().endswith(("{\n", '"explanation"', '"sql"')):
            logger.error(
                "compose: LLM response TRUNCATED (finish_reason=%s, ends_with=%r) — "
                "model output limit reached. Asking user to simplify.",
                response.finish_reason,
                raw_content[-50:] if raw_content else None,
            )
            return ComposerOutput(
                generated_sql="",  # Empty triggers clarification
                explanation="Query too complex for current model token limits. Please simplify.",
                confidence=0.0,
                tables_used=[],
                assumptions=[],
            )

        try:
            parsed = json.loads(repair_json(raw_content))
        except json.JSONDecodeError:
            logger.warning(
                "compose: JSON parse failed — raw response (first 500 chars): %r",
                raw_content[:500],
            )
            # Try to extract SQL from non-JSON response
            parsed = {
                "sql": _extract_sql_from_text(raw_content),
                "explanation": "Generated SQL query",
                "confidence": 0.5,
                "tables_used": [],
                "assumptions": [],
            }

        sql_value = parsed.get("sql", "").replace("\\n", "\n").replace("\\t", "\t")
        if not sql_value.strip():
            logger.warning(
                "compose: empty SQL after parsing — raw response (first 500 chars): %r "
                "parsed_keys=%s",
                raw_content[:500],
                list(parsed.keys()),
            )

        return ComposerOutput(
            generated_sql=sql_value,
            explanation="",  # Removed to save tokens - not needed
            confidence=1.0 if sql_value else 0.0,  # Binary: have SQL or don't
            tables_used=[],  # Removed to save tokens
            assumptions=[],  # Removed to save tokens
        )


def _extract_sql_from_text(text: str) -> str:
    """Try to extract SQL from a text response that isn't valid JSON."""
    # Look for SQL between code fences
    import re

    match = re.search(r"```sql?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Look for SELECT statement
    match = re.search(r"(SELECT\s+.*)", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip(";")

    return text.strip()
