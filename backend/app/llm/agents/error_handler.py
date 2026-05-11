"""Agent: Error Handler — diagnoses SQL errors and produces corrected SQL."""

import json
from dataclasses import dataclass

from app.llm.base_provider import BaseLLMProvider, LLMConfig, LLMMessage
from app.llm.tracing import traceable
from app.llm.utils import repair_json


@dataclass
class ErrorResolution:
    corrected_sql: str
    explanation: str
    should_retry: bool


_ERROR_SYSTEM_PROMPT_TEMPLATE = (
    "You are a SQL debugging expert. A SQL query failed to execute against"
    " a {dialect_label} database.\n"
    "Your job is to analyze the error and produce a corrected SQL query.\n\n"
    "Rules:\n"
    "- Fix ONLY the issue causing the error. Keep the intent of the original query intact.\n"
    "- Generate ONLY SELECT statements.\n"
    "- Follow {dialect_label} syntax exactly:{dialect_hints}\n"
    "- If the error is unrecoverable (data doesn't exist, permission denied),"
    " set should_retry to false.\n\n"
    'Output format:\n{{"corrected_sql": "THE FIXED SQL",'
    ' "explanation": "What was wrong and how you fixed it", "should_retry": true/false}}'
)

_DIALECT_LABELS = {
    "sqlserver": "SQL Server",
    "postgresql": "PostgreSQL",
}

_DIALECT_HINTS = {
    "sqlserver": (
        " Use SELECT TOP N (not LIMIT). Quote identifiers with [square brackets]."
        " Use GETDATE() not NOW(). Use LEN() not LENGTH()."
    ),
    "postgresql": " Use LIMIT N. Quote identifiers with double quotes. Use NOW().",
}


def _build_system_prompt(dialect: str) -> str:
    label = _DIALECT_LABELS.get(dialect, dialect.upper())
    hints = _DIALECT_HINTS.get(dialect, "")
    return _ERROR_SYSTEM_PROMPT_TEMPLATE.format(dialect_label=label, dialect_hints=hints)


def _compact_schema(schema_tables: dict[str, list[str]]) -> str:
    """Render schema_tables as a compact table(col, col) list — ~200 tokens vs ~4000."""
    if not schema_tables:
        return "(no schema available)"
    lines = [f"{tbl}({', '.join(cols)})" for tbl, cols in schema_tables.items()]
    return "\n".join(lines)


class ErrorHandlerAgent:
    MAX_RETRIES = 3

    def __init__(self, provider: BaseLLMProvider, config: LLMConfig):
        self.provider = provider
        self.config = config

    @traceable(name="agent.handle_error")
    async def handle_error(
        self,
        question: str,
        failed_sql: str,
        error_message: str,
        schema_tables: dict[str, list[str]],
        dialect: str = "sqlserver",
        attempt_number: int = 1,
        previous_attempts: list[str] | None = None,
    ) -> ErrorResolution:
        """Analyze a SQL error and produce corrected SQL.

        Args:
            schema_tables: Compact {TABLE: [col, ...]} dict — NOT the full prompt_context.
                           Keeps the payload small (~200 tokens vs ~4000).
            dialect: SQL dialect string from connector_type (e.g. "sqlserver", "postgresql").
        """
        if attempt_number > self.MAX_RETRIES:
            return ErrorResolution(
                corrected_sql="",
                explanation=f"Max retries ({self.MAX_RETRIES}) exceeded",
                should_retry=False,
            )

        previous = ""
        if previous_attempts:
            previous = "\n\nPrevious failed attempts:\n" + "\n---\n".join(previous_attempts)

        compact_schema = _compact_schema(schema_tables)

        user_prompt = f"""Original question: "{question}"

Failed SQL (attempt {attempt_number}):
{failed_sql}

Error:
{error_message}

Available tables and columns:
{compact_schema}
{previous}

Provide a corrected SQL query. Respond with JSON: corrected_sql, explanation, should_retry."""

        messages = [
            LLMMessage(role="system", content=_build_system_prompt(dialect)),
            LLMMessage(role="user", content=user_prompt),
        ]

        response = await self.provider.complete(messages, self.config)

        try:
            parsed = json.loads(repair_json(response.content))
        except json.JSONDecodeError:
            # Try to extract SQL from the response
            import re

            match = re.search(r"```sql?\s*\n?(.*?)\n?```", response.content, re.DOTALL)
            sql = match.group(1).strip() if match else ""
            parsed = {
                "corrected_sql": sql,
                "explanation": response.content,
                "should_retry": bool(sql),
            }

        return ErrorResolution(
            corrected_sql=parsed.get("corrected_sql", ""),
            explanation=parsed.get("explanation", ""),
            should_retry=parsed.get("should_retry", False),
        )
