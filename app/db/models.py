"""
MongoDB document models and operations.

Defines the structure of documents in each collection
and provides typed operations for CRUD.
"""

from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr
from bson import ObjectId

from .connection import get_database


# ============================================
# Pydantic Models
# ============================================
# Use str for MongoDB _id in Pydantic models (we pass str(doc["_id"]) when building).
# PyObjectId was removed to avoid Pydantic v2 validator signature mismatch.


class UserInDB(BaseModel):
    """User document as stored in MongoDB."""
    id: Optional[str] = Field(default=None, alias="_id")
    firstName: str
    lastName: str
    email: EmailStr
    passwordHash: str
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lastLoginAt: Optional[datetime] = None
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str, datetime: lambda v: v.isoformat()}


class UserPublic(BaseModel):
    """User data safe to return to frontend (no password)."""
    id: str
    firstName: str
    lastName: str
    email: str
    createdAt: datetime
    lastLoginAt: Optional[datetime] = None


class ActionItemInDB(BaseModel):
    """Action item sub-document."""
    description: str
    owner: Optional[str] = None


class MeetingInDB(BaseModel):
    """Meeting document as stored in MongoDB."""
    id: Optional[str] = Field(default=None, alias="_id")
    userId: str
    fileName: str
    language: str
    summary: str
    transcript: str
    transcriptClean: str
    participants: List[str] = []
    decisions: List[str] = []
    actionItems: List[ActionItemInDB] = []
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str, datetime: lambda v: v.isoformat()}


class UsageInDB(BaseModel):
    """Usage tracking document."""
    id: Optional[str] = Field(default=None, alias="_id")
    userId: str
    date: str  # "YYYY-MM-DD" format
    count: int = 0
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


# ============================================
# User Operations
# ============================================

class User:
    """User collection operations."""
    
    @staticmethod
    async def create(
        first_name: str,
        last_name: str,
        email: str,
        password_hash: str,
    ) -> Optional[UserPublic]:
        """Create a new user. Returns None if email already exists."""
        db = get_database()
        if db is None:
            return None
        
        doc = {
            "firstName": first_name,
            "lastName": last_name,
            "email": email.lower(),
            "passwordHash": password_hash,
            "createdAt": datetime.now(timezone.utc),
            "lastLoginAt": None,
        }
        
        try:
            result = await db.users.insert_one(doc)
            return UserPublic(
                id=str(result.inserted_id),
                firstName=first_name,
                lastName=last_name,
                email=email.lower(),
                createdAt=doc["createdAt"],
                lastLoginAt=None,
            )
        except Exception as e:
            # Duplicate key error if email exists
            if "duplicate key" in str(e).lower():
                return None
            raise
    
    @staticmethod
    async def find_by_email(email: str) -> Optional[UserInDB]:
        """Find user by email."""
        db = get_database()
        if db is None:
            return None
        
        doc = await db.users.find_one({"email": email.lower()})
        if doc is None:
            return None
        
        return UserInDB(
            _id=str(doc["_id"]),
            firstName=doc["firstName"],
            lastName=doc["lastName"],
            email=doc["email"],
            passwordHash=doc["passwordHash"],
            createdAt=doc["createdAt"],
            lastLoginAt=doc.get("lastLoginAt"),
        )
    
    @staticmethod
    async def find_by_id(user_id: str) -> Optional[UserPublic]:
        """Find user by ID."""
        db = get_database()
        if db is None:
            return None
        
        try:
            doc = await db.users.find_one({"_id": ObjectId(user_id)})
            if doc is None:
                return None
            
            return UserPublic(
                id=str(doc["_id"]),
                firstName=doc["firstName"],
                lastName=doc["lastName"],
                email=doc["email"],
                createdAt=doc["createdAt"],
                lastLoginAt=doc.get("lastLoginAt"),
            )
        except Exception:
            return None
    
    @staticmethod
    async def update_last_login(user_id: str) -> None:
        """Update user's last login timestamp."""
        db = get_database()
        if db is None:
            return
        
        try:
            await db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"lastLoginAt": datetime.now(timezone.utc)}}
            )
        except Exception:
            pass


# ============================================
# Meeting Operations
# ============================================

class Meeting:
    """Meeting collection operations."""
    
    @staticmethod
    async def create(
        user_id: str,
        file_name: str,
        language: str,
        summary: str,
        transcript: str,
        transcript_clean: str,
        participants: List[str],
        decisions: List[str],
        action_items: List[dict],
    ) -> Optional[str]:
        """Create a new meeting. Returns meeting ID."""
        db = get_database()
        if db is None:
            return None
        
        doc = {
            "userId": user_id,
            "fileName": file_name,
            "language": language,
            "summary": summary,
            "transcript": transcript,
            "transcriptClean": transcript_clean,
            "participants": participants,
            "decisions": decisions,
            "actionItems": action_items,
            "createdAt": datetime.now(timezone.utc),
        }
        
        result = await db.meetings.insert_one(doc)
        return str(result.inserted_id)
    
    @staticmethod
    async def create_many(meetings: List[dict]) -> int:
        """Bulk create meetings. Returns count created."""
        db = get_database()
        if db is None or not meetings:
            return 0
        
        result = await db.meetings.insert_many(meetings)
        return len(result.inserted_ids)
    
    @staticmethod
    async def find_by_user(user_id: str, limit: int = 100) -> List[MeetingInDB]:
        """Get all meetings for a user, newest first."""
        db = get_database()
        if db is None:
            return []
        
        cursor = db.meetings.find({"userId": user_id}).sort("createdAt", -1).limit(limit)
        results = []
        async for doc in cursor:
            results.append(MeetingInDB(
                _id=str(doc["_id"]),
                userId=doc["userId"],
                fileName=doc["fileName"],
                language=doc["language"],
                summary=doc["summary"],
                transcript=doc["transcript"],
                transcriptClean=doc.get("transcriptClean", ""),
                participants=doc.get("participants", []),
                decisions=doc.get("decisions", []),
                actionItems=[
                    ActionItemInDB(
                        description=ai.get("description", ""),
                        owner=ai.get("owner")
                    )
                    for ai in doc.get("actionItems", [])
                ],
                createdAt=doc["createdAt"],
            ))
        return results
    
    @staticmethod
    async def delete(meeting_id: str, user_id: str) -> bool:
        """Delete a meeting. Returns True if deleted."""
        db = get_database()
        if db is None:
            return False
        
        try:
            result = await db.meetings.delete_one({
                "_id": ObjectId(meeting_id),
                "userId": user_id,
            })
            return result.deleted_count > 0
        except Exception:
            return False


# ============================================
# Usage Operations
# ============================================

class Usage:
    """Usage tracking operations."""
    
    @staticmethod
    def _get_today() -> str:
        """Get today's date string."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    @staticmethod
    async def get(user_id: str) -> int:
        """Get usage count for today."""
        db = get_database()
        if db is None:
            return 0
        
        doc = await db.usage.find_one({
            "userId": user_id,
            "date": Usage._get_today(),
        })
        
        return doc["count"] if doc else 0
    
    @staticmethod
    async def increment(user_id: str) -> int:
        """Increment usage count for today. Returns new count."""
        db = get_database()
        if db is None:
            return 0
        
        today = Usage._get_today()
        
        result = await db.usage.find_one_and_update(
            {"userId": user_id, "date": today},
            {"$inc": {"count": 1}},
            upsert=True,
            return_document=True,
        )
        
        return result["count"] if result else 1
    
    @staticmethod
    async def can_use(user_id: str, limit: int) -> bool:
        """Check if user can make another request."""
        current = await Usage.get(user_id)
        return current < limit
