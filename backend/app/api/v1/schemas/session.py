from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SessionCreate(BaseModel):
    connection_id: UUID
    title: str = "New Chat"


class SessionResponse(BaseModel):
    id: UUID
    connection_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class SessionMessageResponse(BaseModel):
    id: UUID
    connection_id: UUID
    session_id: UUID | None
    natural_language: str
    turn_type: str = "query"
    clarification_reason: str | None = None
    generated_sql: str | None
    final_sql: str | None
    execution_status: str
    error_message: str | None
    row_count: int | None
    execution_time_ms: float | None
    retry_count: int
    result_summary: str | None
    result_columns: list[str] | None = None
    result_preview_rows: list[list] | None = None
    is_favorite: bool
    created_at: datetime

    model_config = {"from_attributes": True}
