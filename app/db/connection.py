"""
MongoDB connection management.

Uses Motor for async MongoDB operations with FastAPI.
Connection is lazily initialized and reused across requests.
"""

import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional

from app.config.settings import settings


logger = logging.getLogger("speechi.db")

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
        logger.warning("[DB] MONGODB_URI not set, database features disabled")
        return
    
    try:
        _client = AsyncIOMotorClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=5000,
        )
        _database = _client[settings.mongodb_db_name]
        
        # Test connection
        await _client.admin.command("ping")
        logger.info("[DB] Connected to MongoDB: %s", settings.mongodb_db_name)
        
        # Create indexes
        await _create_indexes()
        
    except Exception as e:
        logger.error("[DB] Failed to connect to MongoDB: %s", e)
        _client = None
        _database = None


async def _create_indexes() -> None:
    """Create necessary indexes for collections."""
    if _database is None:
        return
    
    # Users collection: unique email index
    await _database.users.create_index("email", unique=True)
    logger.debug("[DB] Created index: users.email (unique)")
    
    # Meetings collection: userId index for queries
    await _database.meetings.create_index("userId")
    logger.debug("[DB] Created index: meetings.userId")
    
    # Usage collection: compound index for userId + date
    await _database.usage.create_index([("userId", 1), ("date", 1)], unique=True)
    logger.debug("[DB] Created index: usage.userId_date (unique)")


async def close_db() -> None:
    """
    Close MongoDB connection.
    
    Call this on application shutdown.
    """
    global _client, _database
    
    if _client:
        _client.close()
        logger.info("[DB] MongoDB connection closed")
    
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
