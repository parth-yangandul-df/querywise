"""Auth endpoints — login + JWT issuance via HttpOnly cookies."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.core.limiter import limiter
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit_service import log_audit_from_request

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str  # Returned in body so clients can pass it to the chatbot via cross-origin cookie exchange
    email: str
    role: str
    resource_id: int | None
    employee_id: str | None


class CookieTokenRequest(BaseModel):
    token: str


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Authenticate with email + password.

    Sets JWT in an HttpOnly cookie and a readable csrf_token cookie.
    Also returns the token in the response body so clients (e.g. Angular test
    app) can pass it to the chatbot via cross-origin cookie exchange via POST /auth/cookie.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user: User | None = result.scalar_one_or_none()

    # Constant-time check: always verify even if user is None to prevent timing attacks
    password_bytes = body.password.encode("utf-8")
    dummy_hash = b"$2b$12$000000000000000000000000000000000000000000000000000000000"

    stored_hash = user.hashed_password.encode("utf-8") if user else dummy_hash

    try:
        password_matches = bcrypt.checkpw(password_bytes, stored_hash)
    except Exception:
        password_matches = False

    if not user or not user.is_active or not password_matches:
        await log_audit_from_request(
            db,
            request,
            action="login",
            status="failure",
            user_email=body.email,
            details={"reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Issue JWT
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=settings.jwt_expiry_seconds)

    payload: dict = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "resource_id": user.resource_id,
        "employee_id": user.employee_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }

    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    csrf_token = secrets.token_hex(32)
    is_secure = settings.environment != "development"

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="strict",
        secure=is_secure,
        max_age=settings.jwt_expiry_seconds,
        path="/",
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,  # Must be readable by JS to send as X-CSRF-Token header
        samesite="strict",
        secure=is_secure,
        max_age=settings.jwt_expiry_seconds,
        path="/",
    )

    await log_audit_from_request(
        db,
        request,
        action="login",
        status="success",
        user_id=str(user.id),
        user_email=user.email,
    )

    return LoginResponse(
        access_token=token,
        email=user.email,
        role=user.role,
        resource_id=user.resource_id,
        employee_id=user.employee_id,
    )


@router.get("/me", response_model=LoginResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
) -> LoginResponse:
    """Return current user info. Used by the frontend to verify cookie validity on boot."""
    return LoginResponse(
        access_token="",
        email=current_user.email,
        role=current_user.role,
        resource_id=current_user.resource_id,
        employee_id=current_user.employee_id,
    )


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear auth cookies to end the session."""
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="csrf_token", path="/")
    return {"detail": "Logged out"}


@router.post("/refresh")
@limiter.limit("10/minute")
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Refresh an existing JWT token.

    Accepts a valid (non-expired) token from the cookie and issues a new one.
    This allows users to stay logged in without re-entering credentials.
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No token provided. Please log in.",
        )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired. Please log in again.",
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token. Please log in again.",
        ) from None

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user: User | None = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    now = datetime.now(UTC)
    exp = now + timedelta(seconds=settings.jwt_expiry_seconds)

    new_payload: dict = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "resource_id": user.resource_id,
        "employee_id": user.employee_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }

    new_token = jwt.encode(new_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    csrf_token = secrets.token_hex(32)
    is_secure = settings.environment != "development"

    response.set_cookie(
        key="access_token",
        value=new_token,
        httponly=True,
        samesite="strict",
        secure=is_secure,
        max_age=settings.jwt_expiry_seconds,
        path="/",
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        samesite="strict",
        secure=is_secure,
        max_age=settings.jwt_expiry_seconds,
        path="/",
    )

    await log_audit_from_request(
        db,
        request,
        action="token_refresh",
        status="success",
        user_id=str(user.id),
        user_email=user.email,
    )

    return LoginResponse(
        access_token=new_token,
        email=user.email,
        role=user.role,
        resource_id=user.resource_id,
        employee_id=user.employee_id,
    )


@router.post("/cookie")
async def set_cookie_from_token(
    request: Request,
    body: CookieTokenRequest,
    response: Response,
) -> dict:
    """Accept a JWT in the request body and set it as an HttpOnly cookie.

    Used by the standalone chatbot page: the parent app passes the token here
    after obtaining it through its own auth flow, establishing a cookie session
    for all subsequent chatbot API calls.
    """
    # Validate Origin header in production to prevent cross-origin token exchange
    if settings.environment != "development":
        origin = request.headers.get("origin")
        allowed_origins = {o.rstrip("/") for o in settings.cors_origins}
        if not origin or origin.rstrip("/") not in allowed_origins:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid origin",
            )

    # Validate the token is a well-formed JWT before setting it
    try:
        payload = jwt.decode(
            body.token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None

    csrf_token = secrets.token_hex(32)
    is_secure = settings.environment != "development"

    # Calculate remaining TTL from token expiry
    remaining_seconds = max(0, int(payload.get("exp", 0) - datetime.now(UTC).timestamp()))

    response.set_cookie(
        key="access_token",
        value=body.token,
        httponly=True,
        samesite="strict",
        secure=is_secure,
        max_age=remaining_seconds or settings.jwt_expiry_seconds,
        path="/",
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        samesite="strict",
        secure=is_secure,
        max_age=remaining_seconds or settings.jwt_expiry_seconds,
        path="/",
    )

    return {"detail": "Cookie session established"}
