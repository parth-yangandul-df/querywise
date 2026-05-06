"""Shared retry configuration for LLM provider calls.

Uses tenacity for exponential backoff with jitter on transient failures.
Retry is applied to: rate limits, connection errors, and server errors.
"""

from __future__ import annotations

import logging
from typing import Any

from loguru import logger
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import settings
from app.core.exceptions import RateLimitError as AppRateLimitError

# Exception types that warrant a retry
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
    AppRateLimitError,
)


def llm_retry(
    max_attempts: int | None = None,
    retryable_exceptions: tuple[type[Exception], ...] = RETRYABLE_EXCEPTIONS,
) -> Any:
    """Return a tenacity retry decorator configured for LLM calls.

    Args:
        max_attempts: Override max retry attempts. Defaults to settings.max_retry_attempts.
        retryable_exceptions: Exception types that should trigger a retry.

    Returns:
        A tenacity retry decorator.
    """
    attempts = max_attempts or settings.max_retry_attempts

    return retry(
        retry=retry_if_exception_type(retryable_exceptions),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=1, max=30, jitter=2),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
