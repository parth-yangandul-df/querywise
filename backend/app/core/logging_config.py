"""Centralized logging configuration using loguru + JSONL + rotation.

Intercepts all stdlib ``logging`` calls and routes them through loguru so
existing ``logging.getLogger(__name__)`` patterns across the codebase
continue to work without modification.

Outputs:
  - JSONL to stderr (console, INFO+)
  - JSONL to daily rotating file (backend/logs/, DEBUG+)
"""

from __future__ import annotations

import contextvars
import datetime as _dt
import gzip
import json
import logging
import sys
from pathlib import Path
from uuid import uuid4

from loguru import logger

# ---------------------------------------------------------------------------
# JSONL formatter
# ---------------------------------------------------------------------------


def _format_record(record: dict) -> str:
    """Format a log record as a single JSON line (no trailing newline).

    Semantic fields follow the project convention:
    timestamp, level, component, operation, operation_status, trace_id,
    message, context, metrics, error.
    """
    extra = record.get("extra", {})

    log_entry: dict = {
        "timestamp": record["time"].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "level": record["level"].name.lower(),
        "component": record.get("name", record.get("file", "unknown")),
        "operation": extra.get("operation"),
        "operation_status": extra.get("status"),
        "trace_id": extra.get("trace_id"),
        "message": record["message"],
        "context": {
            k: v
            for k, v in extra.items()
            if k not in ("operation", "status", "trace_id", "metrics", "_serialized")
        },
        "metrics": extra.get("metrics"),
        "error": None,
    }

    exc = record.get("exception")
    if exc is not None:
        # stdlib path: exc_info is a (type, value, traceback) tuple
        if isinstance(exc, tuple):
            exc_type, exc_value, _ = exc
            if exc_type is not None:
                log_entry["error"] = {
                    "type": exc_type.__name__,
                    "message": str(exc_value) if exc_value else "Unknown error",
                }
        # loguru path: exc is an ExceptionInfo object with .type / .value
        elif hasattr(exc, "type") and exc.type is not None:
            log_entry["error"] = {
                "type": exc.type.__name__,
                "message": str(exc.value) if exc.value else "Unknown error",
            }

    return json.dumps(log_entry, default=str)


def _console_sink(message: object) -> None:
    """Write a formatted JSONL line directly to stderr (bypasses loguru's format_map)."""
    record = message.record  # type: ignore[attr-defined]
    # Use pre-serialized JSON if available (set by InterceptHandler), else format now
    line = record.get("extra", {}).get("_serialized") or _format_record(record)
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# InterceptHandler — routes stdlib logging through loguru
# ---------------------------------------------------------------------------


class InterceptHandler(logging.Handler):
    """Route stdlib ``logging`` records through loguru.

    Usage::

        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    After this, any ``logging.getLogger("foo").info("...")`` call is
    forwarded to ``logger.opt(depth=depth).log(level, message)``.
    """

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        # Get corresponding loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller depth so loguru reports the original file/line
        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        # Pre-serialize to JSON here so both sinks receive a ready string via
        # extra["_serialized"] — avoids loguru re-processing JSON as a format template.
        # We build a minimal record dict matching _format_record's expected shape.
        _record_dict = {
            "time": _dt.datetime.fromtimestamp(record.created, tz=_dt.UTC),
            "level": type("_L", (), {"name": record.levelname})(),
            "name": record.name,
            "message": record.getMessage(),
            "extra": {},
            "exception": record.exc_info if record.exc_info else None,
        }
        _serialized = _format_record(_record_dict)

        logger.opt(depth=depth, exception=record.exc_info).bind(_serialized=_serialized).log(
            level, record.getMessage()
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_LOG_INITIALIZED = False


def _make_retention_fn(log_dir: Path, compress_after_days: int = 10):
    """Return a loguru retention callable.

    Compresses .jsonl log files older than ``compress_after_days`` days to .gz.
    Never deletes any log file.
    """

    def _retain(files: list) -> None:
        cutoff = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=compress_after_days)
        for filepath in files:
            path = Path(filepath)
            if path.suffix == ".jsonl":
                mtime = _dt.datetime.fromtimestamp(path.stat().st_mtime, tz=_dt.UTC)
                if mtime < cutoff:
                    gz_path = path.with_suffix(".jsonl.gz")
                    try:
                        with path.open("rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                            f_out.writelines(f_in)
                        path.unlink()
                    except Exception:
                        pass  # leave original intact on any error
            # .gz files: never touch

    return _retain


def setup_logging(
    app_name: str = "querywise",
    level: str = "INFO",
    file_enabled: bool = True,
    rotation: str = "10 MB",
    retention: str = "7 days",
) -> None:
    """Configure loguru with JSONL output and stdlib interception.

    Idempotent — safe to call multiple times (e.g. in ``--reload`` mode).

    Parameters
    ----------
    app_name:
        Application name used for the log directory.
    level:
        Minimum log level for console output (``DEBUG``, ``INFO``, …).
    file_enabled:
        Whether to also write logs to a rotating file.
    rotation:
        Log rotation threshold (e.g. ``"10 MB"``).
    retention:
        How long to keep rotated logs (e.g. ``"7 days"``).
    """
    global _LOG_INITIALIZED
    if _LOG_INITIALIZED:
        return
    _LOG_INITIALIZED = True

    # Remove all default loguru handlers
    logger.remove()

    # Console — JSONL to stderr so it doesn't interfere with stdout streams
    logger.add(
        _console_sink,
        level=level,
    )

    # File — daily rotating JSONL to backend/logs/
    if file_enabled:
        # Use project-relative logs directory: backend/logs/
        log_dir = Path(__file__).parent.parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        def _ensure_serialized(record: dict) -> bool:
            """Ensure _serialized is present before the format string is applied.

            Some records (e.g. from spawned processes or direct loguru calls) skip
            InterceptHandler and arrive without _serialized in extra.  We populate
            it here so the format string never raises KeyError.
            """
            if "_serialized" not in record["extra"]:
                record["extra"]["_serialized"] = _format_record(record)
            return True

        # Date-based filename: querywise_2026-04-13.jsonl
        # No enqueue=True so logs are written synchronously (real-time)
        logger.add(
            str(log_dir / f"{app_name}_{{time:YYYY-MM-DD}}.jsonl"),
            format="{extra[_serialized]}\n",
            filter=_ensure_serialized,
            level="DEBUG",
            rotation=rotation,
            retention=retention,
        )

    # Intercept stdlib logging so existing getLogger(__name__) calls work
    logging.basicConfig(
        handlers=[InterceptHandler()],
        level=0,
        force=True,
    )

    # Set log levels for key namespaces
    logging.getLogger("app").setLevel(logging.DEBUG)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# Context variable for propagating request IDs through async call chains
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def set_request_id(request_id: str) -> None:
    """Store the request ID in the current async context for log correlation."""
    _request_id_ctx.set(request_id)


def get_trace_id() -> str:
    """Return the request ID from context if available, otherwise generate a UUID4.

    Falls back to a fresh UUID4 when no request ID has been set in the current
    async context (e.g. background tasks, startup).
    """
    return _request_id_ctx.get() or str(uuid4())
