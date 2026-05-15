"""Shared retry helper with exponential backoff and jitter."""

import asyncio
import logging
import random
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


async def retry_async(
    coro_fn: Any,
    *args: Any,
    retries: int = 1,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    name: str = "operation",
) -> T:
    """Execute a coroutine with exponential-backoff retry.

    Args:
        coro_fn: Async callable (or coroutine) to retry.
        retries: Max retry attempts (total = retries + 1 initial).
        base_delay: Seconds before first retry, doubles each attempt.
        max_delay: Cap on delay between retries.
        retryable_exceptions: Exception types that trigger retry.
        name: Human-readable label for log messages.

    Returns:
        The result of coro_fn.

    Raises:
        The last exception caught if all attempts fail.
        CancelledError is re-raised immediately.
    """
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        try:
            return await coro_fn(*args)
        except asyncio.CancelledError:  # noqa: UP041 — CancelledError keeps asyncio prefix
            raise
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt < retries:
                delay = min(base_delay * (2**attempt), max_delay)
                delay += random.uniform(0, 0.1 * delay)
                logger.warning(
                    "%s attempt %d/%d failed with %s, retrying in %.1fs",
                    name,
                    attempt + 1,
                    retries + 1,
                    exc.__class__.__name__,
                    delay,
                )
                await asyncio.sleep(delay)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                delay = min(base_delay * (2**attempt), max_delay)
                delay += random.uniform(0, 0.1 * delay)
                logger.warning(
                    "%s attempt %d/%d failed with %s, retrying in %.1fs",
                    name,
                    attempt + 1,
                    retries + 1,
                    exc.__class__.__name__,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                break

    assert last_exc is not None
    logger.error("%s failed after %d attempts", name, retries + 1)
    raise last_exc
