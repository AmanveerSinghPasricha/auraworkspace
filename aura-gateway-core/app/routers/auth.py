import os
import logging
import uuid
import httpx
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db import get_db
from app.models.user import User
from app.schemas.auth import (
    UserSignUpRequest,
    UserLoginRequest,
    TokenResponse,
    UserMemoryProfileResponse
)
# Fixed imports to match exact module locations
from app.security import hash_password, verify_password, create_access_token
from app.core.security import encrypt_token

logger = logging.getLogger("auth_router")
router = APIRouter(prefix="/api/v1/auth", tags=["Phase 4: Auth & Integrations"])

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")


# =====================================================================
# REQUEST & RESPONSE SCHEMAS
# =====================================================================
class ConnectSmitheryRequest(BaseModel):
    user_id: str = Field(..., description="Unique ID of the target user in PostgreSQL")
    smithery_connection_id: str = Field(..., description="Smithery OAuth Connection ID")


class ConnectGithubRequest(BaseModel):
    user_id: str = Field(..., description="Unique ID of the target user in PostgreSQL")
    code: str = Field(..., description="Temporary Authorization Code returned by GitHub OAuth")


# =====================================================================
# AUTHENTICATION & CONNECTION ENDPOINTS
# =====================================================================
@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserSignUpRequest, db: AsyncSession = Depends(get_db)):
    """Registers a user, hashes their password, and saves their user profile to PostgreSQL."""
    # 1. Check if user email exists
    result = await db.execute(select(User).where(User.email == payload.email))
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists."
        )

    # 2. Hash password & instantiate User matching model schema attributes exactly
    new_user = User(
        id=str(uuid.uuid4()),  # Assign UUID string for Primary Key
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        smithery_connection_id=None,
        github_access_token=None
    )

    # 3. Save to database
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(f"👤 [AUTH & MEMORY PERSISTED] User '{new_user.id}' created successfully.")

    # 4. Generate JWT
    access_token = create_access_token(data={"sub": new_user.id, "email": new_user.email})

    return TokenResponse(
        access_token=access_token,
        user_id=new_user.id,
        full_name=new_user.full_name or ""
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticates credentials and returns a signed access token."""
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalars().first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials provided."
        )

    access_token = create_access_token(data={"sub": user.id, "email": user.email})

    return TokenResponse(
        access_token=access_token,
        user_id=user.id,
        full_name=user.full_name or ""
    )


@router.get("/memory/profile/{user_id}", response_model=UserMemoryProfileResponse)
async def get_user_memory_profile(user_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieves structured user memory profile for state graph contextualization."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found."
        )

    full_name_str = user.full_name or "N/A"
    summary = f"User Name: {full_name_str}\nEmail: {user.email}"

    return UserMemoryProfileResponse(
        user_id=user.id,
        full_name=full_name_str,
        email=user.email,
        profile_summary=summary
    )


@router.post("/connect-smithery", status_code=status.HTTP_200_OK)
async def connect_smithery_account(
    payload: ConnectSmitheryRequest,
    db: AsyncSession = Depends(get_db)
):
    """Links a user's authenticated Smithery Gmail connection ID to their PostgreSQL user account."""
    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID '{payload.user_id}' not found."
        )

    # Save and commit connection ID
    user.smithery_connection_id = payload.smithery_connection_id
    await db.commit()
    await db.refresh(user)

    logger.info(f"🔗 [SMITHERY OAUTH LINKED] User '{user.id}' bound to connection ID: {payload.smithery_connection_id}")

    return {
        "status": "success",
        "message": "Smithery Gmail connection successfully linked to user account.",
        "user_id": user.id,
        "smithery_connection_id": user.smithery_connection_id
    }


@router.post("/connect-github", status_code=status.HTTP_200_OK)
async def connect_github_account(
    payload: ConnectGithubRequest,
    db: AsyncSession = Depends(get_db)
):
    """Exchanges OAuth authorization code for GitHub Access Token and encrypts it into PostgreSQL."""
    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalars().first()

    # Fallback lookup for default demo UUID if provided user_id is not found
    if not user:
        fallback_res = await db.execute(
            select(User).where(User.id == "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6")
        )
        user = fallback_res.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID '{payload.user_id}' not found."
        )

    # Exchange code with GitHub API
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
        access_token = token_data.get("access_token")

        if not access_token:
            error_msg = token_data.get("error_description", "Invalid OAuth authorization code.")
            raise HTTPException(status_code=400, detail=error_msg)

    # Encrypt token and store in user record
    user.github_access_token = encrypt_token(access_token)
    await db.commit()
    await db.refresh(user)

    logger.info(f"🔑 [GITHUB OAUTH LINKED] Encrypted token saved for User '{user.id}'")

    return {
        "status": "success",
        "message": "GitHub account successfully linked.",
        "user_id": user.id
    }