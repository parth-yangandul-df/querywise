from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.chat_session import ChatSession

TurnType = Literal["query", "clarification", "show_sql", "explain_result"]
ClarificationReason = Literal[
    "low_confidence_rewrite",
    "retry_exhausted",
    "missing_previous_turn",
    "missing_previous_sql",
    "missing_previous_result",
]


class QueryExecution(Base):
    __tablename__ = "query_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("database_connections.id"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    natural_language: Mapped[str] = mapped_column(Text, nullable=False)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    final_sql: Mapped[str | None] = mapped_column(Text)
    execution_status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    execution_time_ms: Mapped[float | None] = mapped_column(Float)
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    llm_model: Mapped[str | None] = mapped_column(String(100))
    llm_input_tokens: Mapped[int | None] = mapped_column(Integer)
    llm_output_tokens: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    result_summary: Mapped[str | None] = mapped_column(Text)
    turn_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Agentic multi-turn fields
    turn_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="query")
    clarification_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    result_columns: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    result_preview_rows: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Relationship back to session
    session: Mapped["ChatSession | None"] = relationship(
        "ChatSession", back_populates="executions"
    )
