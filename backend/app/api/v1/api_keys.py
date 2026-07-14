"""
API Keys management router.
"""

import secrets
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...database import get_db
from ...models.user import User
from ...models.api_key import ApiKey
from ...dependencies import get_current_user

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


class ApiKeyCreateRequest(BaseModel):
    name: str


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key: str  # Masked or plain depending on context
    is_active: bool = True
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all API keys for the current user, masked for security."""
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user.id)
        .order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()

    response = []
    for k in keys:
        # Mask the key: e.g. lr_abcd...wxyz -> lr_••••••••wxyz
        raw_key = k.key
        masked_key = raw_key
        if len(raw_key) > 8:
            prefix = raw_key[:3]  # "lr_"
            suffix = raw_key[-4:]
            masked_key = f"{prefix}••••••••{suffix}"
        
        response.append(ApiKeyResponse(
            id=k.id,
            name=k.name,
            key=masked_key,
            is_active=k.is_active,
            created_at=k.created_at,
        ))

    return response


@router.post("", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: ApiKeyCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key. The unmasked key is returned only once."""
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Tên API Key không được để trống.")

    # Generate key: lr_ + 32 secure chars
    token = secrets.token_urlsafe(24)  # ~32 chars long
    generated_key = f"lr_{token}"

    new_key = ApiKey(
        user_id=user.id,
        name=data.name,
        key=generated_key,
    )
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    return ApiKeyResponse(
        id=new_key.id,
        name=new_key.name,
        key=generated_key,  # Plain key shown once
        created_at=new_key.created_at,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke and delete an API key."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key không tồn tại hoặc không thuộc quyền sở hữu của bạn.",
        )

    await db.delete(api_key)
    await db.commit()


@router.post("/{key_id}/regenerate", response_model=ApiKeyResponse)
async def regenerate_api_key(
    key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate (replace) the key value. Returns the new plain key once."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key không tồn tại hoặc không thuộc quyền sở hữu của bạn.",
        )

    # Generate new key
    new_token = secrets.token_urlsafe(24)
    new_key = f"lr_{new_token}"
    api_key.key = new_key
    api_key.is_active = True
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key=new_key,  # Plain key shown once
        created_at=api_key.created_at,
    )


@router.patch("/{key_id}/toggle")
async def toggle_api_key(
    key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle active/inactive status of an API key."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key không tồn tại hoặc không thuộc quyền sở hữu của bạn.",
        )

    api_key.is_active = not api_key.is_active
    await db.commit()
    await db.refresh(api_key)

    return {
        "id": api_key.id,
        "is_active": api_key.is_active,
    }
