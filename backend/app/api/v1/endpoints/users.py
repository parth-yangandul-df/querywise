"""User management endpoints — admin only."""

import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.api.v1.schemas.user import UserCreate, UserResponse, UserUpdate
from app.db.models.user import User
from app.db.session import get_db

ALLOWED_UPDATE_FIELDS: frozenset[str] = frozenset(
    {"email", "role", "resource_id", "employee_id", "is_active"}
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """List all users — admin only."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Create a new user — admin only."""
    # Check email not exists
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")

    # Hash password
    password_bytes = body.password.encode("utf-8")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))

    user = User(
        id=uuid.uuid4(),
        email=body.email,
        hashed_password=hashed.decode("utf-8"),
        role=body.role,
        resource_id=body.resource_id,
        employee_id=body.employee_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Update a user — admin only. Cannot update own account."""
    # Cannot update yourself
    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot update your own account")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    update_data = body.model_dump(exclude_unset=True)
    if "password" in update_data:
        password_bytes = update_data.pop("password").encode("utf-8")
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))
        user.hashed_password = hashed.decode("utf-8")

    for field, value in update_data.items():
        if field not in ALLOWED_UPDATE_FIELDS:
            continue
        if field == "email":
            result = await db.execute(select(User).where(User.email == value, User.id != user_id))
            if result.scalar_one_or_none():
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Deactivate a user (soft delete) — admin only. Cannot deactivate yourself."""
    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot deactivate your own account")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    user.is_active = False
    await db.commit()
