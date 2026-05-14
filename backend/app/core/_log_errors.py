"""Structured error logging helpers."""

import logging


def log_db_error(
    logger: logging.Logger,
    exc: Exception,
    sqlstate: str = "?",
    pgcode: str = "?",
    connection_id: object = None,
    query: str | None = None,
) -> None:
    """Log a database error with structured SQLSTATE and pgcode fields."""
    logger.warning(
        "DB error sqlstate=%s pgcode=%s conn=%s query=%.200s",
        sqlstate,
        pgcode,
        connection_id,
        query or "?",
        exc_info=exc,
    )
