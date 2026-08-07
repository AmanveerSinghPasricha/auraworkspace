"""
Integrations Router - Gmail Dynamic OAuth Management
===================================================
Provides routes for generating connection authorization URLs and handling Smithery callbacks.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models.user import User
from app.config import settings

logger = logging.getLogger("integrations_router")
router = APIRouter(prefix="/api/v1/integrations/gmail", tags=["Integrations"])


class CallbackPayload(BaseModel):
    user_id: str
    connection_id: str


class ConnectUrlResponse(BaseModel):
    connect_url: str


@router.get("/connect-url", response_model=ConnectUrlResponse)
async def get_gmail_connect_url(
    user_id: str, 
    db: AsyncSession = Depends(get_db)
):
    """
    Constructs the Smithery dynamic OAuth redirect URL for the given user.
    """
    # Verify user exists
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"User with ID '{user_id}' not found."
        )

    connect_url = (
        f"https://smithery.ai/connect/gmail"
        f"?client_id={settings.SMITHERY_CLIENT_ID}"
        f"&user_id={user_id}"
    )
    
    logger.info(f"🔗 [OAUTH] Generated Smithery connect URL for user: {user_id}")
    return ConnectUrlResponse(connect_url=connect_url)


@router.post("/callback", status_code=status.HTTP_200_OK)
async def save_gmail_callback(
    payload: CallbackPayload, 
    db: AsyncSession = Depends(get_db)
):
    """
    Persists the connection_id issued by Smithery upon successful user OAuth consent.
    """
    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"User with ID '{payload.user_id}' not found."
        )

    user.smithery_connection_id = payload.connection_id
    await db.commit()
    await db.refresh(user)

    logger.info(f"💾 [OAUTH CALLBACK] Persisted connection_id '{payload.connection_id}' for user '{payload.user_id}'")
    return {
        "status": "success", 
        "message": "Gmail integration successfully linked.",
        "user_id": user.id,
        "connection_id": user.smithery_connection_id
    }