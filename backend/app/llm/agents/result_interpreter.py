"""Agent: Result Interpreter — converts query results into human-readable answers."""

import json
from dataclasses import dataclass

from app.llm.base_provider import BaseLLMProvider, LLMConfig, LLMMessage
from app.llm.prompts.interpreter_prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.llm.tracing import traceable
from app.llm.utils import repair_json


@dataclass
class InterpretationOutput:
    summary: str
    suggested_followups: list[str]


def format_single_value_result(rows: list[list]) -> str | None:
    """Return a display-ready scalar when the query produced exactly one cell."""
    if len(rows) != 1:
        return None

    row = rows[0]
    if len(row) != 1:
        return None

    value = row[0]
    if value is None:
        return "NULL"
    return str(value)


class ResultInterpreterAgent:
    def __init__(self, provider: BaseLLMProvider, config: LLMConfig):
        self.provider = provider
        self.config = config

    @traceable(name="agent.interpret_results")
    async def interpret(
        self,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[list],
        row_count: int,
    ) -> InterpretationOutput:
        """Convert raw query results into a human-readable answer."""
        # Build a preview of the results (limit to avoid huge prompts)
        results_preview = _format_results_preview(columns, rows, max_rows=5)

        user_prompt = USER_PROMPT_TEMPLATE.format(
            question=question,
            sql=sql,
            row_count=row_count,
            columns=", ".join(columns),
            results_preview=results_preview,
        )

        messages = [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        response = await self.provider.complete(messages, self.config)

        # Track token usage and cost in MLflow
        from app.core.mlflow_tracing import set_mlflow_llm_cost

        set_mlflow_llm_cost(
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            provider=self.provider.provider_type.value,
        )

        try:
            parsed = json.loads(repair_json(response.content))
        except json.JSONDecodeError:
            # Fallback: use the raw response as the summary
            parsed = {
                "summary": response.content,
                "suggested_followups": [],
            }

        return InterpretationOutput(
            summary=parsed.get("summary", response.content),
            suggested_followups=parsed.get("suggested_followups", []),
        )


def _format_results_preview(
    columns: list[str],
    rows: list[list],
    max_rows: int = 20,
) -> str:
    """Format query results as a readable text table for the LLM."""
    if not rows:
        return "(no results)"

    preview_rows = rows[:max_rows]
    lines = []

    # Header
    lines.append(" | ".join(columns))
    lines.append("-" * len(lines[0]))

    # Rows
    for row in preview_rows:
        lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))

    if len(rows) > max_rows:
        lines.append(f"... and {len(rows) - max_rows} more rows")

    return "\n".join(lines)
