from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    connection_id: UUID
    question: str = Field(min_length=1, max_length=1000)
    session_id: UUID | None = None
    clear_context: bool = Field(
        default=False,
        description="Explicitly clear prior context — resets session history for this query",
    )


class ExecuteSQLRequest(BaseModel):
    connection_id: UUID
    sql: str = Field(min_length=1, max_length=10000)
    original_question: str | None = None  # for history tracking


class QueryResponse(BaseModel):
    id: UUID | None = None
    question: str
    turn_type: str = "query"
    clarification_message: str | None = None
    clarification_options: list[str] = Field(default_factory=list)
    generated_sql: str | None = None
    final_sql: str | None = None
    explanation: str | None = None
    columns: list[str] = Field(default_factory=list)
    column_types: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float | None = None
    truncated: bool = False
    summary: str | None = None
    highlights: list[str] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)
    llm_provider: str | None = None
    llm_model: str | None = None
    retry_count: int = 0


class SQLOnlyResponse(BaseModel):
    generated_sql: str
    explanation: str
    confidence: float
    tables_used: list[str]
    assumptions: list[str]


class QueryHistoryResponse(BaseModel):
    id: UUID
    connection_id: UUID
    natural_language: str
    generated_sql: str | None
    final_sql: str | None
    execution_status: str
    error_message: str | None
    row_count: int | None
    execution_time_ms: float | None
    retry_count: int
    result_summary: str | None
    is_favorite: bool
    created_at: datetime

    model_config = {"from_attributes": True}
