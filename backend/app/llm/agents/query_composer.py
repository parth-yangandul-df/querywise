"""Agent: Query Composer — converts NL questions to SQL."""

import json
from dataclasses import dataclass

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

        # Parse JSON response (repair handles common Ollama/local model issues)
        try:
            parsed = json.loads(repair_json(response.content))
        except json.JSONDecodeError:
            # Try to extract SQL from non-JSON response
            parsed = {
                "sql": _extract_sql_from_text(response.content),
                "explanation": "Generated SQL query",
                "confidence": 0.5,
                "tables_used": [],
                "assumptions": [],
            }

        return ComposerOutput(
            generated_sql=parsed.get("sql", "").replace("\\n", "\n").replace("\\t", "\t"),
            explanation=parsed.get("explanation", ""),
            confidence=parsed.get("confidence", 0.5),
            tables_used=parsed.get("tables_used", []),
            assumptions=parsed.get("assumptions", []),
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
