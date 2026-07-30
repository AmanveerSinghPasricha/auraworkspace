from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List

class UserSignUpRequest(BaseModel):
    # Credentials
    email: EmailStr
    password: str = Field(..., min_length=8, description="User password (min 8 characters)")
    full_name: str = Field(..., description="Full Name")

    # Long-Term Memory Profiling Questionnaire
    role_or_title: str = Field(..., description="e.g., Security Analyst, Software Engineer, Executive")
    primary_goal: str = Field(..., description="Primary reason for using Aura AI")
    preferred_tone: str = Field("Direct & Concise", description="Direct & Concise, Detailed & Technical, Conversational")
    domain_expertise: List[str] = Field(default_factory=list, description="e.g., ['NIST', 'FastAPI', 'AWS']")
    additional_context: Optional[str] = Field(None, description="Custom facts or rules the AI should always remember")


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    full_name: str


class UserMemoryProfileResponse(BaseModel):
    user_id: str
    full_name: str
    role_or_title: str
    primary_goal: str
    preferred_tone: str
    domain_expertise: List[str]
    additional_context: Optional[str]
    profile_summary: str