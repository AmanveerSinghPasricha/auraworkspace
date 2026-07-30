import logging
from fastapi import APIRouter, HTTPException, status, Depends
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
from app.core.security import hash_password, verify_password, create_access_token

logger = logging.getLogger("auth_router")
router = APIRouter(prefix="/api/v1/auth", tags=["Phase 4: Auth & Memory Ingestion"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserSignUpRequest, db: AsyncSession = Depends(get_db)):
    """Registers a user, hashes their password, and saves their long-term memory questionnaire to PostgreSQL."""
    # 1. Check if user email exists
    result = await db.execute(select(User).where(User.email == payload.email))
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists."
        )

    # 2. Hash password & instantiate User
    new_user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role_or_title=payload.role_or_title,
        primary_goal=payload.primary_goal,
        preferred_tone=payload.preferred_tone,
        domain_expertise=payload.domain_expertise,
        additional_context=payload.additional_context,
    )

    # 3. Save to database
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(f"👤 [AUTH & MEMORY PERSISTED] User '{new_user.id}' created with long-term memory traits.")

    # 4. Generate JWT
    access_token = create_access_token(data={"sub": new_user.id, "email": new_user.email})

    return TokenResponse(
        access_token=access_token,
        user_id=new_user.id,
        full_name=new_user.full_name
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticates credentials and returns a signed access token."""
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalars().first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials provided."
        )

    access_token = create_access_token(data={"sub": user.id, "email": user.email})

    return TokenResponse(
        access_token=access_token,
        user_id=user.id,
        full_name=user.full_name
    )


@router.get("/memory/profile/{user_id}", response_model=UserMemoryProfileResponse)
async def get_user_memory_profile(user_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieves structured user memory to inject directly into system prompts for chat nodes."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User memory profile not found."
        )

    expertise_str = ", ".join(user.domain_expertise) if user.domain_expertise else "None specified"
    summary = (
        f"User Name: {user.full_name}\n"
        f"Role/Title: {user.role_or_title}\n"
        f"Primary Goal: {user.primary_goal}\n"
        f"Communication Tone: {user.preferred_tone}\n"
        f"Domain Expertise: {expertise_str}\n"
        f"Custom Memory Notes: {user.additional_context or 'None'}"
    )

    return UserMemoryProfileResponse(
        user_id=user.id,
        full_name=user.full_name,
        role_or_title=user.role_or_title,
        primary_goal=user.primary_goal,
        preferred_tone=user.preferred_tone,
        domain_expertise=user.domain_expertise or [],
        additional_context=user.additional_context,
        profile_summary=summary
    )