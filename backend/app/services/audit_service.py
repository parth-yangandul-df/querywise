"""Audit logging service for security event tracking."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


@dataclass
class AuditContext:
    """Context for audit logging."""

    user_id: str | None = None
    user_email: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


async def log_audit(
    db: AsyncSession,
    action: str,
    status: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    context: AuditContext | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log an audit event to the database.

    Args:
        db: Database session
        action: Action type (e.g., "login", "query", "connection_create")
        status: Status ("success", "failure", "unauthorized")
        resource_type: Type of resource (e.g., "connection", "user", "session")
        resource_id: ID of the resource
        context: User context (user_id, email, IP, user agent)
        details: Additional details as key-value pairs
    """
    try:
        audit_log = AuditLog(
            user_id=context.user_id if context else None,
            user_email=context.user_email if context else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            ip_address=context.ip_address if context else None,
            user_agent=context.user_agent if context else None,
            details=details,
        )
        db.add(audit_log)
        await db.flush()
        logger.debug("Audit logged: action=%s status=%s", action, status)
    except Exception:
        logger.warning("Failed to write audit log (non-critical)", exc_info=True)


async def log_audit_from_request(
    db: AsyncSession,
    request: Any,
    action: str,
    status: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    user_id: str | None = None,
    user_email: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log an audit event extracting request context.

    Args:
        db: Database session
        request: FastAPI request object
        action: Action type
        status: Status
        resource_type: Type of resource
        resource_id: ID of the resource
        user_id: User ID if authenticated
        user_email: User email if authenticated
        details: Additional details
    """
    context = AuditContext(
        user_id=user_id,
        user_email=user_email,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await log_audit(
        db=db,
        action=action,
        status=status,
        resource_type=resource_type,
        resource_id=resource_id,
        context=context,
        details=details,
    )