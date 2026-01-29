"""
Authentication service.

Handles password hashing, JWT token creation/verification,
and user authentication middleware.

Uses the bcrypt library directly (not passlib) for compatibility
with bcrypt 4.1+. Bcrypt has a 72-byte limit; we truncate to 72 bytes
when hashing/verifying.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from app.config.settings import settings
from app.db.models import User, UserPublic


# Bcrypt limit in bytes (bcrypt truncates beyond this)
BCRYPT_MAX_PASSWORD_BYTES = 72

# Bearer token security
security = HTTPBearer(auto_error=False)


# ============================================
# Password Operations
# ============================================

def _password_bytes(password: str) -> bytes:
    """Encode password to bytes and truncate to bcrypt's 72-byte limit."""
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_PASSWORD_BYTES:
        return raw[:BCRYPT_MAX_PASSWORD_BYTES]
    return raw


def hash_password(password: str) -> str:
    """Hash a password using bcrypt. Passwords longer than 72 bytes are truncated."""
    pw_bytes = _password_bytes(password)
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pw_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    pw_bytes = _password_bytes(plain_password)
    try:
        return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))
    except Exception:
        return False


# ============================================
# JWT Operations
# ============================================

def create_access_token(user_id: str, email: str) -> str:
    """
    Create a JWT access token.
    
    Args:
        user_id: The user's database ID
        email: The user's email
    
    Returns:
        Encoded JWT token
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    
    payload = {
        "sub": user_id,
        "email": email,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and validate a JWT token.
    
    Args:
        token: The JWT token string
    
    Returns:
        Token payload dict or None if invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError:
        return None


# ============================================
# Dependency: Get Current User
# ============================================

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[UserPublic]:
    """
    Dependency to get the current authenticated user.
    
    Returns None if no valid token is provided.
    For endpoints that require auth, check if return is None.
    """
    if credentials is None:
        return None
    
    token = credentials.credentials
    payload = decode_access_token(token)
    
    if payload is None:
        return None
    
    user_id = payload.get("sub")
    if user_id is None:
        return None
    
    # Fetch user from database
    user = await User.find_by_id(user_id)
    return user


async def require_auth(
    user: Optional[UserPublic] = Depends(get_current_user),
) -> UserPublic:
    """
    Dependency that requires authentication.
    
    Raises 401 if user is not authenticated.
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ============================================
# Token Extraction Helper
# ============================================

def extract_token_from_request(request: Request) -> Optional[str]:
    """
    Extract Bearer token from request headers.
    
    Used for manual token extraction when needed.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None
