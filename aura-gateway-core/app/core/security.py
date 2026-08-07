import os
import logging
import base64
from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

logger = logging.getLogger("security")

# Password Hashing Context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Fallback Fernet key if ENCRYPTION_KEY is not set in env
SECRET_KEY = os.getenv("ENCRYPTION_KEY", os.getenv("SECRET_KEY", "aura_secret_key_32_bytes_long_exact!!"))


# ==========================================
# 🔑 Password Hashing & Verification
# ==========================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against its hashed counterpart."""
    if not plain_password or not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as exc:
        logger.error(f"❌ Password verification error: {exc}")
        return False

def verify_password_hash(plain_password: str, hashed_password: str) -> bool:
    """Alias for verify_password to support legacy callers."""
    return verify_password(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hashes a plain text password using bcrypt."""
    return pwd_context.hash(password)


# ==========================================
# 🔐 OAuth Token Encryption & Decryption
# ==========================================

def get_fernet_instance() -> Fernet:
    """Constructs a urlsafe-base64 Fernet instance from the 32-byte SECRET_KEY."""
    try:
        key_bytes = SECRET_KEY.encode()
        if len(key_bytes) < 32:
            key_bytes = key_bytes.ljust(32, b'0')
        elif len(key_bytes) > 32:
            key_bytes = key_bytes[:32]
        
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        return Fernet(fernet_key)
    except Exception as exc:
        logger.error(f"❌ Failed to construct Fernet instance: {exc}")
        raise exc

def encrypt_token(raw_token: str) -> str:
    """Encrypts a raw OAuth token string."""
    if not raw_token:
        return ""
    try:
        fernet = get_fernet_instance()
        return fernet.encrypt(raw_token.encode()).decode()
    except Exception as exc:
        logger.error(f"⚠️ Encryption failed: {exc}")
        return raw_token

def decrypt_token(encrypted_token: str) -> str:
    """Decrypts an encrypted OAuth token string with fallback for raw unencrypted tokens."""
    if not encrypted_token:
        return ""
    
    # If token starts with standard GitHub OAuth prefixes, it's already raw/unencrypted
    if encrypted_token.startswith(("ghp_", "gho_", "ghu_", "ghs_", "ghr_")):
        return encrypted_token

    try:
        fernet = get_fernet_instance()
        return fernet.decrypt(encrypted_token.encode()).decode()
    except (InvalidToken, Exception) as exc:
        logger.warning(f"⚠️ Fernet decryption failed ({exc}). Assuming raw token fallback...")
        return encrypted_token