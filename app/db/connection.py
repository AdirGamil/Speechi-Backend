"""
MongoDB connection management.

Uses Motor for async MongoDB operations with FastAPI.
Connection is lazily initialized and reused across requests.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional

from app.config.settings import settings


# Global client instance
_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None


async def init_db() -> None:
    """
    Initialize MongoDB connection.
    
    Call this on application startup.
    Creates indexes for collections.
    """
    global _client, _database
    
    if not settings.mongodb_uri:
        print("[DB] WARNING: MONGODB_URI not set, database features disabled")
        return
    
    try:
        _client = AsyncIOMotorClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=5000,
        )
        _database = _client[settings.mongodb_db_name]
        
        # Test connection
        await _client.admin.command("ping")
        print(f"[DB] Connected to MongoDB: {settings.mongodb_db_name}")
        
        # Create indexes
        await _create_indexes()
        
    except Exception as e:
        print(f"[DB] ERROR: Failed to connect to MongoDB: {e}")
        _client = None
        _database = None


async def _create_indexes() -> None:
    """Create necessary indexes for collections."""
    if _database is None:
        return
    
    # Users collection: unique email index
    await _database.users.create_index("email", unique=True)
    print("[DB] Created index: users.email (unique)")
    
    # Meetings collection: userId index for queries
    await _database.meetings.create_index("userId")
    print("[DB] Created index: meetings.userId")
    
    # Usage collection: compound index for userId + date
    await _database.usage.create_index([("userId", 1), ("date", 1)], unique=True)
    print("[DB] Created index: usage.userId_date (unique)")


async def close_db() -> None:
    """
    Close MongoDB connection.
    
    Call this on application shutdown.
    """
    global _client, _database
    
    if _client:
        _client.close()
        print("[DB] MongoDB connection closed")
    
    _client = None
    _database = None


def get_database() -> Optional[AsyncIOMotorDatabase]:
    """
    Get the database instance.
    
    Returns None if not connected.
    """
    return _database


def is_connected() -> bool:
    """Check if database is connected."""
    return _database is not None
