"""
Authentication API routes.

Endpoints for user registration, login, and profile management.
All auth-related routes are here.
"""

from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.config.settings import settings
from app.db.models import User, UserPublic, Meeting, Usage
from app.services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_auth,
)


router = APIRouter(prefix="/auth", tags=["auth"])


# ============================================
# Request/Response Models
# ============================================

class RegisterRequest(BaseModel):
    """Registration request body."""
    firstName: str = Field(..., min_length=1, max_length=50)
    lastName: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)
    confirmPassword: str = Field(..., min_length=6, max_length=100)
    
    @field_validator("firstName", "lastName")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()
    
    @field_validator("confirmPassword")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class LoginRequest(BaseModel):
    """Login request body."""
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    """Successful auth response with user and token."""
    user: UserPublic
    token: str
    usage: dict  # { usedToday, dailyLimit }


class MigrateMeetingsRequest(BaseModel):
    """Request to migrate guest meetings to user account."""
    meetings: List[dict]


class UsageResponse(BaseModel):
    """Usage statistics response."""
    usedToday: int
    dailyLimit: int
    canUse: bool


# ============================================
# Routes
# ============================================

@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest):
    """
    Register a new user.
    
    Creates user account, issues JWT token.
    Returns user profile and token.
    """
    # Check if email already exists
    existing = await User.find_by_email(body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Hash password
    password_hash = hash_password(body.password)
    
    # Create user
    user = await User.create(
        first_name=body.firstName,
        last_name=body.lastName,
        email=body.email,
        password_hash=password_hash,
    )
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )
    
    # Create token
    token = create_access_token(user.id, user.email)
    
    # Get usage (will be 0 for new user)
    used_today = await Usage.get(user.id)
    
    return AuthResponse(
        user=user,
        token=token,
        usage={
            "usedToday": used_today,
            "dailyLimit": settings.registered_daily_limit,
        },
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    """
    Login with email and password.
    
    Validates credentials, issues JWT token.
    Returns user profile and token.
    """
    # Find user
    user_db = await User.find_by_email(body.email)
    if user_db is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Verify password
    if not verify_password(body.password, user_db.passwordHash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Use string id everywhere for safe serialization
    user_id = str(user_db.id)
    
    # Update last login (non-blocking)
    await User.update_last_login(user_id)
    
    # Create token
    token = create_access_token(user_id, user_db.email)
    
    # Get usage
    used_today = await Usage.get(user_id)
    
    # Build public user with explicit str/datetime for JSON
    now_utc = datetime.now(timezone.utc)
    user_public = UserPublic(
        id=user_id,
        firstName=user_db.firstName,
        lastName=user_db.lastName,
        email=user_db.email,
        createdAt=user_db.createdAt,
        lastLoginAt=now_utc,
    )
    
    return AuthResponse(
        user=user_public,
        token=token,
        usage={
            "usedToday": used_today,
            "dailyLimit": settings.registered_daily_limit,
        },
    )


@router.get("/me", response_model=AuthResponse)
async def get_me(user: UserPublic = Depends(require_auth)):
    """
    Get current user profile.
    
    Requires authentication.
    Returns user profile and current usage.
    """
    # Get usage
    used_today = await Usage.get(user.id)
    
    # Return fresh token for session extension
    token = create_access_token(user.id, user.email)
    
    return AuthResponse(
        user=user,
        token=token,
        usage={
            "usedToday": used_today,
            "dailyLimit": settings.registered_daily_limit,
        },
    )


@router.get("/usage", response_model=UsageResponse)
async def get_usage(user: Optional[UserPublic] = Depends(get_current_user)):
    """
    Get usage statistics.
    
    Works for both authenticated and guest users.
    """
    if user:
        used_today = await Usage.get(user.id)
        limit = settings.registered_daily_limit
    else:
        # Guest - return 0, limit checking is done client-side
        used_today = 0
        limit = settings.guest_daily_limit
    
    return UsageResponse(
        usedToday=used_today,
        dailyLimit=limit,
        canUse=used_today < limit,
    )


@router.post("/migrate-meetings")
async def migrate_meetings(
    body: MigrateMeetingsRequest,
    user: UserPublic = Depends(require_auth),
):
    """
    Migrate guest meetings to user account.
    
    Called after registration to preserve guest history.
    """
    if not body.meetings:
        return {"migrated": 0}
    
    # Prepare meetings for insertion
    docs = []
    for m in body.meetings:
        doc = {
            "userId": user.id,
            "fileName": m.get("fileName", "Unknown"),
            "language": m.get("outputLanguage", "en"),
            "summary": m.get("summary", ""),
            "transcript": m.get("transcriptRaw", ""),
            "transcriptClean": m.get("transcriptClean", ""),
            "participants": m.get("participants", []),
            "decisions": m.get("decisions", []),
            "actionItems": [
                {"description": ai.get("description", ""), "owner": ai.get("owner")}
                for ai in m.get("actionItems", [])
            ],
            "createdAt": datetime.fromisoformat(m["createdAt"].replace("Z", "+00:00"))
            if m.get("createdAt") else datetime.now(timezone.utc),
        }
        docs.append(doc)
    
    count = await Meeting.create_many(docs)
    
    return {"migrated": count}


@router.get("/meetings")
async def get_meetings(user: UserPublic = Depends(require_auth)):
    """
    Get all meetings for the authenticated user.
    """
    meetings = await Meeting.find_by_user(user.id)
    
    # Convert to frontend format
    result = []
    for m in meetings:
        result.append({
            "id": m.id,
            "fileName": m.fileName,
            "outputLanguage": m.language,
            "summary": m.summary,
            "transcriptRaw": m.transcript,
            "transcriptClean": m.transcriptClean,
            "participants": m.participants,
            "decisions": m.decisions,
            "actionItems": [
                {"description": ai.description, "owner": ai.owner}
                for ai in m.actionItems
            ],
            "createdAt": m.createdAt.isoformat(),
            "exports": {"word": False, "pdf": False},  # Track client-side
        })
    
    return {"meetings": result}


@router.delete("/meetings/{meeting_id}")
async def delete_meeting(
    meeting_id: str,
    user: UserPublic = Depends(require_auth),
):
    """
    Delete a meeting.
    """
    deleted = await Meeting.delete(meeting_id, user.id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )
    
    return {"deleted": True}
