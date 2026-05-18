"""
ASKA WhatsApp Bot - Clients Package
"""

from app.clients.whatsapp_client import (
    WhatsAppClient,
    WhatsAppClientError,
    MediaExpiredError,
    whatsapp_client
)
from app.clients.gdrive_client import (
    GoogleDriveClient,
    GoogleDriveError,
    gdrive_client
)
from app.clients.gemini_client import (
    GeminiClient,
    GeminiError,
    RateLimitError,
    gemini_client
)

__all__ = [
    # WhatsApp
    "WhatsAppClient",
    "WhatsAppClientError",
    "MediaExpiredError",
    "whatsapp_client",
    # Google Drive
    "GoogleDriveClient",
    "GoogleDriveError",
    "gdrive_client",
    # Gemini
    "GeminiClient",
    "GeminiError",
    "RateLimitError",
    "gemini_client",
]
