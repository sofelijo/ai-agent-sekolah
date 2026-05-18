"""
ASKA WhatsApp Bot - WhatsApp Cloud API Client
Handles all interactions with WhatsApp Cloud API including
sending messages and downloading media.
"""

import logging
import httpx
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class WhatsAppClientError(Exception):
    """Custom exception for WhatsApp API errors."""
    pass


class MediaExpiredError(WhatsAppClientError):
    """Exception when media URL has expired."""
    pass


class WhatsAppClient:
    """
    Client for WhatsApp Cloud API.
    Handles message sending and media downloading.
    """
    
    def __init__(self):
        self.access_token = settings.whatsapp_access_token
        self.phone_number_id = settings.whatsapp_phone_number_id
        self.api_version = settings.whatsapp_api_version
        self.base_url = settings.whatsapp_api_base_url
        self.messages_url = settings.whatsapp_messages_url
        
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
    
    async def get_media_url(self, media_id: str) -> str:
        """
        Get the download URL for a media file.
        
        Args:
            media_id: The media ID from the message
            
        Returns:
            The temporary download URL for the media
            
        Raises:
            WhatsAppClientError: If the API request fails
            MediaExpiredError: If the media has expired
        """
        url = f"{self.base_url}/{media_id}"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, timeout=30.0)
                response.raise_for_status()
                
                data = response.json()
                media_url = data.get("url")
                
                if not media_url:
                    raise WhatsAppClientError("No URL in media response")
                
                logger.info(f"Got media URL for {media_id}")
                return media_url
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise MediaExpiredError(f"Media {media_id} not found or expired")
                raise WhatsAppClientError(f"Failed to get media URL: {e}")
            except Exception as e:
                raise WhatsAppClientError(f"Failed to get media URL: {e}")
    
    async def download_media(self, media_id: str) -> bytes:
        """
        Download media file from WhatsApp.
        
        Args:
            media_id: The media ID from the message
            
        Returns:
            The binary content of the media file
            
        Raises:
            WhatsAppClientError: If download fails
            MediaExpiredError: If the media has expired
        """
        # First, get the media URL
        media_url = await self.get_media_url(media_id)
        
        # Then download the actual file
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    media_url,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    timeout=60.0,
                    follow_redirects=True
                )
                response.raise_for_status()
                
                content = response.content
                logger.info(f"Downloaded media {media_id}: {len(content)} bytes")
                return content
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (404, 410):
                    raise MediaExpiredError(f"Media URL expired for {media_id}")
                raise WhatsAppClientError(f"Failed to download media: {e}")
            except Exception as e:
                raise WhatsAppClientError(f"Failed to download media: {e}")
    
    async def send_text_message(
        self,
        to: str,
        text: str,
        reply_to_message_id: Optional[str] = None
    ) -> dict:
        """
        Send a text message to a WhatsApp number or group.
        
        Args:
            to: The recipient's WhatsApp ID
            text: The message text
            reply_to_message_id: Optional message ID to reply to
            
        Returns:
            The API response as dict
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": text
            }
        }
        
        # Add reply context if provided
        if reply_to_message_id:
            payload["context"] = {
                "message_id": reply_to_message_id
            }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.messages_url,
                    headers=self.headers,
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                
                result = response.json()
                logger.info(f"Sent message to {to}")
                return result
                
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                raise WhatsAppClientError(f"Failed to send message: {e}")
    
    async def send_reply(
        self,
        to: str,
        reply_to_message_id: str,
        text: str
    ) -> dict:
        """
        Convenience method to send a reply message.
        
        Args:
            to: The recipient's WhatsApp ID
            reply_to_message_id: The message ID to reply to
            text: The reply text
            
        Returns:
            The API response as dict
        """
        return await self.send_text_message(
            to=to,
            text=text,
            reply_to_message_id=reply_to_message_id
        )


# Global client instance
whatsapp_client = WhatsAppClient()
