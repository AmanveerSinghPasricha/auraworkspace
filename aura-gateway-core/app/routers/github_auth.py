import os
import logging
import httpx
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db, AsyncSessionLocal
from app.models.user import User
from app.core.security import encrypt_token

logger = logging.getLogger("github_auth_router")
router = APIRouter(prefix="/api/v1/auth", tags=["GitHub Integration"])

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")

class ConnectGithubRequest(BaseModel):
    user_id: str = Field(..., description="Target user UUID")
    code: str = Field(..., description="Temporary GitHub OAuth authorization code")

@router.post("/connect-github", status_code=status.HTTP_200_OK)
async def connect_github_account(
    payload: ConnectGithubRequest,
    db: AsyncSession = Depends(get_db)
):
    """Exchanges authorization code for GitHub access token and saves encrypted token to Postgres."""
    logger.info(f"🔑 [GITHUB OAUTH] Processing authorization code for User: {payload.user_id}")

    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GITHUB_CLIENT_ID or GITHUB_CLIENT_SECRET is missing in environment variables."
        )

    # 1. Exchange code with GitHub OAuth API
    token_url = "https://github.com/login/oauth/access_token"
    headers = {"Accept": "application/json"}
    body = {
        "client_id": GITHUB_CLIENT_ID,
        "client_secret": GITHUB_CLIENT_SECRET,
        "code": payload.code
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, json=body, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange authorization code with GitHub.")

        token_data = response.json()
        raw_access_token = token_data.get("access_token")

        if not raw_access_token:
            error_msg = token_data.get("error_description", "Invalid or expired OAuth authorization code.")
            raise HTTPException(status_code=400, detail=error_msg)

    # 2. Encrypt token
    encrypted_token = encrypt_token(raw_access_token)

    # 3. Lookup user record in PostgreSQL and persist token
    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalars().first()

    # Fallback to demo user ID if provided ID isn't found
    if not user:
        fallback_res = await db.execute(select(User).where(User.id == "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6"))
        user = fallback_res.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User ID '{payload.user_id}' not found in database."
        )

    user.github_access_token = encrypted_token
    await db.commit()
    await db.refresh(user)

    logger.info(f"✅ [GITHUB OAUTH LINKED] Successfully stored encrypted token for User '{user.id}'")

    return {
        "status": "success",
        "message": "GitHub account successfully linked.",
        "user_id": user.id
    }