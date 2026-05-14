# Global Error Handling Overhaul

## Status

Draft — spec for implementation.

## Goal

A layered error handling system where every error category is caught, classified, and handled at the right layer. The user should almost never see a raw retry button — common failures self-heal or route to actionable messages.

## Unified Error Response Schema

All responses (HTTP + SSE) share this shape:

```json
{
  "error": "Service temporarily unavailable. Please try again.",
  "code": 503,
  "category": "db.pool_exhausted",
  "retryable": true,
  "retry_after_seconds": 5
}
```

SSE prefix: same fields + `"type": "error"`.

---

## Phase 1 — Core Infrastructure

### 1.1 Extend AppError

**File:** `app/core/exceptions.py`

Current `AppError.__init__`: `(message, status_code)`.

Change to: `(message, status_code, *, category="pipeline.unknown", retryable=False, retry_after_seconds=None)`.

Update `to_response_content()` and `to_stream_event()` to emit all 5 fields.

Subclass mapping:

| Exception | Code | Category | Retryable | After |
|---|---|---|---|---|
| InternalServerError | 500 | `pipeline.unknown` | false | — |
| NotFoundError | 404 | `resource.not_found` | false | — |
| ValidationError | 422 | `input.validation` | false | — |
| SQLSafetyError | 403 | `db.safety_violation` | false | — |
| QueryTimeoutError | 408 | `db.query_timeout` | true | 5 |
| RateLimitError | 429 | `llm.rate_limited` | true | Response header |
| ConnectionError | 502 | `db.connection` | true | 3 |
| ServiceUnavailableError | 503 | `service.unavailable` | true | 5 |
| AuthenticationError | 401 | `auth.unauthorized` | false | — |
| PermissionError | 403 | `auth.forbidden` | false | — |
| BadRequestError | 400 | `input.bad_request` | false | — |

New subclasses:

| Exception | Code | Category | Retryable | After |
|---|---|---|---|---|
| PoolExhaustedError(ServiceUnavailableError) | 503 | `db.pool_exhausted` | true | 5 |
| SchemaCacheStaleError(ServiceUnavailableError) | 503 | `db.schema_stale` | true | (auto-retry once) |
| EmbeddingError(ServiceUnavailableError) | 503 | `llm.embedding_failed` | true | 5 |

Extend `raise_if_provider_rate_limited` to classify more codes and keywords:

```python
def raise_if_provider_rate_limited(exc, provider_name):
    status = _extract_status(exc)
    body = _extract_body(exc)
    match status:
        case 408: raise QueryTimeoutError(30)
        case 429: raise RateLimitError(...)
        case 402: raise BadRequestError("Insufficient credits...")
        case 401 | 403: raise AuthenticationError(...)
        case 502 | 503 | 529: raise ServiceUnavailableError(...)
    if body and "overloaded" in body.lower():
        raise ServiceUnavailableError("LLM provider is overloaded...")
```

Update `sanitize_error` to pass new fields.

### 1.2 Shared retry helper

**File:** `app/core/_retry.py` — NEW

```python
async def retry_async(
    coro_fn: Callable[..., Coroutine],
    *args,
    retries: int = 1,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    name: str = "operation",
) -> T:
```

- Exponential backoff: `delay = min(base_delay * (2 ** attempt), max_delay)`
- Jitter: `delay += random.uniform(0, 0.1 * delay)`
- `CancelledError` re-raised immediately
- Logs each attempt with attempt number and delay
- Last exception re-raised if all attempts fail

Used by: glossary_resolver retry, embedding retry, any ad-hoc retry.

### 1.3 Register global exception handlers

**File:** `app/core/exception_handlers.py`

Add new imports:
- `asyncpg.exceptions` (`ConnectionDoesNotExistError`, `OutdatedSchemaCacheError`, `QueryCanceledError`, `PostgresError`)
- `sqlalchemy.exc.DBAPIError`, `TimeoutError` as `PoolTimeoutError`
- `asyncio.CancelledError`
- `httpx`

New handlers in order:

| Exception | Maps to | Log level |
|---|---|---|
| `asyncio.CancelledError` | Silent debug log, empty JSON | DEBUG |
| `DBAPIError` | Inspect `exc.orig`, route to subclass | WARNING |
| `httpx.HTTPStatusError` | Route by status code | WARNING |
| `httpx.ConnectError` | `ConnectionError(...)` | WARNING |
| `httpx.TimeoutException` | `QueryTimeoutError(30)` | WARNING |
| Pool timeout from sqlalchemy | `PoolExhaustedError()` | WARNING |

DBAPIError mapping logic:
```python
orig = exc.orig
if isinstance(orig, asyncpg.exceptions.QueryCanceledError):
    app_exc = QueryTimeoutError(30)
elif isinstance(orig, asyncpg.exceptions.ConnectionDoesNotExistError):
    app_exc = ConnectionError(...)
elif "timeout" in str(orig).lower():
    app_exc = QueryTimeoutError(30)
else:
    app_exc = InternalServerError(...)

logger.warning("DB error (sqlstate=%s, pgcode=%s)", getattr(orig, "sqlstate", "?"), getattr(orig, "pgcode", "?"))
```

Update `AppError` handler to log `category` as well.

Update catch-all unhandled handler to return 5-field schema.

---

## Phase 2 — Per-Layer Error Classification

### 2.1 PostgreSQL connector

**File:** `app/connectors/postgresql/connector.py`

- Pool acquire in `connect()`: currently bare `except Exception` catching pool creation — change to catch `asyncpg.CannotConnectNowError` separately from generic failure.
- `execute_query()`: already catches `asyncpg.QueryCanceledError` → `QueryTimeoutError`. No other SQLSTATE handling needed for the existing code (the global DBAPIError handler in `exception_handlers.py` catches anything that escapes).
- Add structured logging with `sqlstate`/`pgcode` to the existing `except` blocks.

SQL Server connector: minimal change — just ensure existing exception paths log structured data.

### 2.2 LLM retry

**File:** `app/llm/retry.py`

Add httpx types to `RETRYABLE_EXCEPTIONS`:

```python
import httpx

RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
    AppRateLimitError,
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.ProtocolError,
)
```

Note: `httpx.ConnectError` subclasses `ConnectionError`, but being explicit is clearer.

### 2.3 Embedding retry

**File:** `app/services/embedding_service.py`

Wrap the provider call in a 2-attempt retry:

```python
@mlflow_span("embed_text", span_type="EMBEDDING", capture_output=False)
async def embed_text(text: str) -> list[float]:
    # ... caching unchanged ...

    provider = _get_provider()
    embedding = await _embed_with_retry(provider, text)

    # ... caching unchanged ...


async def _embed_with_retry(provider, text: str) -> list[float]:
    for attempt in range(2):
        try:
            return await asyncio.wait_for(
                provider.generate_embedding(text), timeout=1.5
            )
        except asyncio.TimeoutError:
            logger.warning("embed_text timeout attempt %d/2", attempt + 1)
        except Exception:
            logger.warning("embed_text failed attempt %d/2", attempt + 1, exc_info=True)
    logger.error("embed_text failed after 2 attempts, using keyword fallback")
    raise EmbeddingError()
```

The `EmbeddingError` propagates to `context_builder.py` which wraps the call and falls back to keyword search.

---

## Phase 3 — SSE Error Events

### 3.1 Structured SSE errors

**File:** `app/api/v1/endpoints/query.py`

The `except AppError` block already calls `exc.to_stream_event()` (5-field schema is included by default now).

The `except Exception` catch-all block: update to 5-field schema:

```python
except Exception:
    logger.error("Query stream error", exc_info=True)
    yield _encode_stream_event({
        "type": "error",
        "error": "Something went wrong. Please try again.",
        "code": 500,
        "category": "pipeline.unknown",
        "retryable": False,
        "retry_after_seconds": None,
    })
```

`CancelledError` handling: change so it doesn't re-raise. Instead, silently clean up:

```python
except asyncio.CancelledError:
    query_task.cancel()
    logger.debug("Query stream cancelled by client")
    return
```

This prevents a bare `CancelledError` propagating to the ASGI server (FastAPI handles it, but log noise).

---

## Phase 4 — Angular Smart Retry UI

### 4.1 Extend types

**File:** `angular-test/src/app/services/chat.service.ts`

```typescript
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content?: string;
  result?: QueryResult;
  errorMessage?: string;
  errorCategory?: string;
  errorRetryable?: boolean;
  errorRetryAfterSeconds?: number | null;
}
```

### 4.2 Update SSE error parsing

In the `sendMessage` catch block:

```typescript
} else if (event.type === 'error') {
  const err = event as any;
  throw {
    message: err.error || err.message || 'An error occurred',
    category: err.category || 'pipeline.unknown',
    retryable: err.retryable ?? false,
    retryAfterSeconds: err.retry_after_seconds ?? null,
  };
}
```

In the outer catch:

```typescript
} catch (e: unknown) {
  if (e instanceof Error && e.name === 'AbortError') {
    this.messages.update(msgs => msgs.filter(m => m.id !== userMsg.id));
  } else if (typeof e === 'object' && e !== null && 'retryable' in e) {
    const err = e as any;
    const errorMsgBubble: ChatMessage = {
      id: `${Date.now()}-error`,
      role: 'error',
      errorMessage: err.message,
      errorCategory: err.category,
      errorRetryable: err.retryable,
      errorRetryAfterSeconds: err.retryAfterSeconds,
    };
    this.messages.update(msgs => [...msgs, errorMsgBubble]);
  } else {
    const errorMsg = e instanceof Error ? e.message : 'An unexpected error occurred';
    this.messages.update(msgs => [...msgs, {
      id: `${Date.now()}-error`,
      role: 'error',
      errorMessage: errorMsg,
      errorRetryable: false,
    }]);
  }
}
```

### 4.3 Smart error component

**File:** `angular-test/src/app/chat/error-bubble.component.ts` — NEW

Three states:

| State | Condition | UI |
|---|---|---|
| Retry | `retryable && !retryAfterSeconds` | Error + "Retry" button |
| Countdown | `retryAfterSeconds > 0` | Error + "Retry in Xs" button |
| Support | `!retryable` | Error + "Contact support" link |

Countdown: `setInterval` decrementing `currentCount`. Button disabled until 0, then click re-sends last question.

Integrate into `chat.component.html`: render error bubble with `(retry)="retry()"` emitter.

---

## Phase 5 — Structured Error Logging

### 5.1 Logging helper

**File:** `app/core/_log_errors.py` — NEW (lightweight)

```python
import logging

def log_db_error(logger, exc, sqlstate, pgcode, connection_id=None, query=None):
    logger.warning(
        "DB error sqlstate=%s pgcode=%s conn=%s query=%.200s",
        sqlstate, pgcode, connection_id, query or "?",
    )
```

Integrated into `exception_handlers.py` DBAPIError handler and `connectors/postgresql/connector.py` catch blocks.

---

## Summary of Changes

| File | Change type | What |
|---|---|---|
| `app/core/exceptions.py` | Modify | category/retryable/after fields; 3 new subclasses; extend classifier |
| `app/core/_retry.py` | NEW | shared `retry_async()` |
| `app/core/_log_errors.py` | NEW | `log_db_error()` helper |
| `app/core/exception_handlers.py` | Modify | CancelledError, DBAPIError, httpx, pool timeout handlers; 5-field schema |
| `app/connectors/postgresql/connector.py` | Modify | Structured logging in catch blocks |
| `app/llm/retry.py` | Modify | httpx types in RETRYABLE_EXCEPTIONS |
| `app/services/embedding_service.py` | Modify | 2-attempt/1.5s retry + EmbeddingError |
| `app/api/v1/endpoints/query.py` | Modify | 5-field catch-all; CancelledError silent return |
| `angular-test/.../chat.service.ts` | Modify | Error metadata, SSE structured error parsing |
| `angular-test/.../error-bubble.component.ts` | NEW | Smart retry UI (3 states) |
| `angular-test/.../chat.component.html` | Modify | Error bubble integration |

## Out of Scope (deferred)

- Model fallback chains (tenacity retry is sufficient)
- Mid-stream LLM retry with resume
- Resumable explanation retry (Phase 2 item)
