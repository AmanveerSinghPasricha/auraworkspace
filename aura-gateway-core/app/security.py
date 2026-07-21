"""
Aura Gateway Core - Security & Authentication Layer

Provides password hashing/validation via pwdlib (Argon2) and JWT token
encoding/decoding via PyJWT for secure API access.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict
import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, status
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

# Dynamically resolve .env path relative to security.py location
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if not ENV_PATH.exists():
    ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

load_dotenv(dotenv_path=ENV_PATH)

# Retrieve Security Configuration from Environment Variables
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "default_fallback_secret_key_change_me")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# Initialize Password Hash Context using Argon2
password_hash_context = PasswordHash((Argon2Hasher(),))


def hash_password(plain_password: str) -> str:
    """
    Hashes a plain text password using the Argon2 hashing algorithm.

    Args:
        plain_password (str): Raw user password.

    Returns:
        str: Securely salted and hashed password string.
    """
    return password_hash_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plain text password against an Argon2 hashed password.

    Args:
        plain_password (str): Raw user password attempt.
        hashed_password (str): Stored Argon2 hash.

    Returns:
        bool: True if password matches, False otherwise.
    """
    return password_hash_context.verify(plain_password, hashed_password)


def create_access_token(data: Dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """
    Encodes a JWT access token containing client payloads and expiration claims.

    Args:
        data (Dict[str, Any]): Claims to embed in the token (e.g., {"sub": user_id}).
        expires_delta (timedelta | None): Custom lifetime duration. Defaults to env configuration.

    Returns:
        str: Signed JWT string.
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes and validates a JWT access token.

    Args:
        token (str): Encoded JWT string.

    Returns:
        Dict[str, Any]: Decoded token payload.

    Raises:
        HTTPException: 401 Unauthorized if token is expired or signature invalid.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials / Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )