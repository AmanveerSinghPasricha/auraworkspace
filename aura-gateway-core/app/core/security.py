import os
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

# Modern password hasher using pwdlib (bypasses passlib Python 3.13 / bcrypt 4.x bug)
password_hash = PasswordHash((BcryptHasher(),))

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "aura-gateway-production-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

def hash_password(password: str) -> str:
    """Hashes password safely, ensuring max length <= 72 bytes for bcrypt compatibility."""
    # Truncate raw password bytes to 72 bytes max for bcrypt standard limits
    safe_password = password.encode("utf-8")[:72].decode("utf-8", errors="ignore")
    return password_hash.hash(safe_password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies plain password against hashed value."""
    safe_password = plain_password.encode("utf-8")[:72].decode("utf-8", errors="ignore")
    return password_hash.verify(safe_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)