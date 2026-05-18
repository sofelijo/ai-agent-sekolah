"""
ASKA WhatsApp Bot - Message Cache
In-memory cache for storing incoming messages with TTL.
Required because WhatsApp API doesn't provide endpoint to fetch message by ID.
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict

from app.config import settings
from app.models.schemas import CachedMessage, MessageType, DocumentMessage

logger = logging.getLogger(__name__)


class MessageCache:
    """
    In-memory cache for WhatsApp messages.
    
    Messages are stored with a TTL (default 24 hours) matching
    WhatsApp's service window. This is necessary because
    WhatsApp Cloud API doesn't provide an endpoint to retrieve
    messages by their ID.
    """
    
    def __init__(self, ttl_hours: int = None):
        self._cache: Dict[str, CachedMessage] = {}
        self._timestamps: Dict[str, datetime] = {}
        self._ttl = timedelta(hours=ttl_hours or settings.cache_ttl_hours)
        self._lock = asyncio.Lock()
    
    async def store(self, message_id: str, message_data: CachedMessage) -> None:
        """
        Store a message in the cache.
        
        Args:
            message_id: The message ID
            message_data: The message data to store
        """
        async with self._lock:
            self._cache[message_id] = message_data
            self._timestamps[message_id] = datetime.now()
            logger.debug(f"Cached message {message_id}")
    
    def store_sync(self, message_id: str, message_data: CachedMessage) -> None:
        """
        Synchronous version of store for use in non-async contexts.
        """
        self._cache[message_id] = message_data
        self._timestamps[message_id] = datetime.now()
        logger.debug(f"Cached message {message_id} (sync)")
    
    def get(self, message_id: str) -> Optional[CachedMessage]:
        """
        Retrieve a message from cache if not expired.
        
        Args:
            message_id: The message ID to retrieve
            
        Returns:
            CachedMessage if found and not expired, None otherwise
        """
        if message_id not in self._cache:
            logger.debug(f"Message {message_id} not in cache")
            return None
        
        # Check expiry
        stored_at = self._timestamps.get(message_id)
        if stored_at and datetime.now() - stored_at > self._ttl:
            # Expired, remove from cache
            logger.debug(f"Message {message_id} expired, removing from cache")
            self._remove(message_id)
            return None
        
        logger.debug(f"Retrieved message {message_id} from cache")
        return self._cache.get(message_id)
    
    def _remove(self, message_id: str) -> None:
        """Remove a message from cache."""
        self._cache.pop(message_id, None)
        self._timestamps.pop(message_id, None)
    
    async def cleanup_expired(self) -> None:
        """
        Background task to periodically clean up expired messages.
        Should be started as a background task on app startup.
        """
        logger.info("Starting message cache cleanup task")
        
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                
                async with self._lock:
                    now = datetime.now()
                    expired_ids = [
                        msg_id for msg_id, ts in self._timestamps.items()
                        if now - ts > self._ttl
                    ]
                    
                    for msg_id in expired_ids:
                        self._remove(msg_id)
                    
                    if expired_ids:
                        logger.info(f"Cleaned up {len(expired_ids)} expired messages")
                        
            except asyncio.CancelledError:
                logger.info("Cache cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in cache cleanup: {e}")
    
    @property
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)
    
    def clear(self) -> None:
        """Clear all cached messages."""
        self._cache.clear()
        self._timestamps.clear()
        logger.info("Message cache cleared")
    
    def store_from_webhook(self, message: dict) -> None:
        """
        Store a message from webhook payload format.
        
        Args:
            message: Raw message dict from webhook
        """
        message_id = message.get("id")
        message_type = message.get("type")
        
        if not message_id:
            return
        
        # Only cache documents and images (media that can be replied to)
        if message_type not in ["document", "image"]:
            return
        
        cached = CachedMessage(
            message_id=message_id,
            sender_id=message.get("from", ""),
            type=MessageType(message_type),
            timestamp=datetime.now()
        )
        
        # Add document info
        if message_type == "document" and message.get("document"):
            doc = message["document"]
            cached.document = DocumentMessage(
                id=doc.get("id", ""),
                mime_type=doc.get("mime_type", ""),
                filename=doc.get("filename"),
                sha256=doc.get("sha256"),
                caption=doc.get("caption")
            )
        
        # Add image info
        if message_type == "image" and message.get("image"):
            img = message["image"]
            from app.models.schemas import ImageMessage
            cached.image = ImageMessage(
                id=img.get("id", ""),
                mime_type=img.get("mime_type", ""),
                sha256=img.get("sha256"),
                caption=img.get("caption")
            )
        
        self.store_sync(message_id, cached)


# Global cache instance
message_cache = MessageCache()
