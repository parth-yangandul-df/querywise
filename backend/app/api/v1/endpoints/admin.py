"""Admin operations — super admin only."""

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.config import settings
from app.db.models.connection import DatabaseConnection
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


class RotateKeyRequest(BaseModel):
    new_key: str


class RotateKeyResponse(BaseModel):
    rotated: int
    failed: int


@router.post("/rotate-encryption-key", response_model=RotateKeyResponse)
async def rotate_encryption_key(
    body: RotateKeyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
) -> RotateKeyResponse:
    """Re-encrypt all connection strings with a new encryption key — admin only.

    Steps:
    1. Validate the new key is a valid Fernet key
    2. For each connection with an encrypted string:
       a. Decrypt with old key
       b. Re-encrypt with new key
    3. Persist all changes atomically
    4. Returns count of rotated and failed entries

    After this succeeds, update ENCRYPTION_KEY in your .env file.
    """
    # Guard: validate new key at the boundary before touching any data
    try:
        new_fernet = Fernet(body.new_key.encode())
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid Fernet key. Generate with: "
                "python -c 'from cryptography.fernet import Fernet;"
                " print(Fernet.generate_key().decode())'"
            ),
        ) from None

    old_fernet = Fernet(settings.encryption_key.encode())

    result = await db.execute(
        select(DatabaseConnection).where(DatabaseConnection.connection_string_encrypted.isnot(None))
    )
    connections = result.scalars().all()

    rotated = 0
    failed = 0

    for conn in connections:
        try:
            plaintext = old_fernet.decrypt(conn.connection_string_encrypted.encode()).decode()
            conn.connection_string_encrypted = new_fernet.encrypt(plaintext.encode()).decode()
            rotated += 1
        except InvalidToken:
            failed += 1
            continue

    await db.commit()
    return RotateKeyResponse(rotated=rotated, failed=failed)
