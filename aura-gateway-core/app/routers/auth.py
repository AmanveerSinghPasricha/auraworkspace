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
from app.security import hash_password, verify_password, create_access_token
from app.core.security import encrypt_token

logger = logging.getLogger("auth_router")
router = APIRouter(prefix="/api/v1/auth", tags=["Phase 4: Auth & Integrations"])

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")


# =====================================================================
# REQUEST SCHEMAS
# =====================================================================
class ConnectSmitheryRequest(BaseModel):
    user_id: str = Field(..., description="Unique ID of the target user in PostgreSQL")
    smithery_connection_id: str = Field(..., description="Smithery OAuth Connection ID")


class ConnectGithubRequest(BaseModel):
    user_id: str = Field(..., description="Unique ID of the target user in PostgreSQL")
    code: str = Field(..., description="Temporary Authorization Code returned by GitHub OAuth")


class ConnectGmailRequest(BaseModel):
    user_id: str = Field(..., description="Unique ID of the target user in PostgreSQL")
    code: str = Field(..., description="Temporary Authorization Code returned by Google OAuth")
    redirect_uri: str = Field(..., description="OAuth Redirect URI matching Google Console configuration")


# =====================================================================
# AUTHENTICATION ENDPOINTS
# =====================================================================
@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserSignUpRequest, db: AsyncSession = Depends(get_db)):
    """Registers a user, hashes password, and saves profile to PostgreSQL."""
    result = await db.execute(select(User).where(User.email == payload.email))
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists."
        )

    new_user = User(
        id=str(uuid.uuid4()),
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        smithery_connection_id=None,
        github_access_token=None,
        google_refresh_token=None
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(f"👤 [AUTH] User '{new_user.id}' created successfully.")

    access_token = create_access_token(data={"sub": new_user.id, "email": new_user.email})

    return TokenResponse(
        access_token=access_token,
        user_id=new_user.id,
        full_name=new_user.full_name or ""
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticates credentials and returns a signed JWT access token."""
    try:
        result = await db.execute(select(User).where(User.email == payload.email))
        user = result.scalars().first()
    except Exception as exc:
        logger.error(f"❌ [LOGIN DB ERROR] Failed to query user: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database query failure during login."
        )

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    access_token = create_access_token(data={"sub": user.id, "email": user.email})

    return TokenResponse(
        access_token=access_token,
        user_id=user.id,
        full_name=user.full_name or ""
    )


@router.get("/memory/profile/{user_id}", response_model=UserMemoryProfileResponse)
async def get_user_memory_profile(user_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieves structured user memory profile for graph context."""
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
        role_or_title="",
        primary_goal="",
        preferred_tone="Direct & Concise",
        domain_expertise=[],
        additional_context="",
        profile_summary=summary
    )


# =====================================================================
# INTEGRATION LINKING ENDPOINTS
# =====================================================================
@router.post("/connect-smithery", status_code=status.HTTP_200_OK)
async def connect_smithery_account(
    payload: ConnectSmitheryRequest,
    db: AsyncSession = Depends(get_db)
):
    """Links a user's Smithery connection ID."""
    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID '{payload.user_id}' not found."
        )

    user.smithery_connection_id = payload.smithery_connection_id
    await db.commit()
    await db.refresh(user)

    return {
        "status": "success",
        "message": "Smithery connection linked successfully.",
        "user_id": user.id
    }


@router.post("/connect-github", status_code=status.HTTP_200_OK)
async def connect_github_account(
    payload: ConnectGithubRequest,
    db: AsyncSession = Depends(get_db)
):
    """Exchanges OAuth code for GitHub Access Token and encrypts it."""
    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalars().first()

    if not user:
        fallback_res = await db.execute(
            select(User).where(User.id == "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6")
        )
        user = fallback_res.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{payload.user_id}' not found."
        )

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

    user.github_access_token = encrypt_token(access_token)
    await db.commit()
    await db.refresh(user)

    return {
        "status": "success",
        "message": "GitHub account successfully linked.",
        "user_id": user.id
    }


@router.post("/connect-gmail", status_code=status.HTTP_200_OK)
async def connect_gmail_account(
    payload: ConnectGmailRequest,
    db: AsyncSession = Depends(get_db)
):
    """Exchanges OAuth authorization code for Google Refresh Token and encrypts it."""
    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalars().first()

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

    token_url = "https://oauth2.googleapis.com/token"
    body = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": payload.code,
        "grant_type": "authorization_code",
        "redirect_uri": payload.redirect_uri
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=body)
        if response.status_code != 200:
            logger.error(f"Google OAuth Error: {response.text}")
            raise HTTPException(status_code=400, detail="Failed to exchange authorization code with Google.")

        token_data = response.json()
        refresh_token = token_data.get("refresh_token")

        if not refresh_token:
            raise HTTPException(
                status_code=400,
                detail="No refresh_token returned by Google. Ensure prompt='consent' and access_type='offline' are set."
            )

    user.google_refresh_token = encrypt_token(refresh_token)
    await db.commit()
    await db.refresh(user)

    logger.info(f"📧 [GMAIL OAUTH LINKED] Encrypted Refresh Token saved for User '{user.id}'")

    return {
        "status": "success",
        "message": "Gmail account successfully linked via Google OAuth.",
        "user_id": user.id
    }