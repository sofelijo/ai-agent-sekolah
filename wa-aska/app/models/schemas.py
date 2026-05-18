"""
ASKA WhatsApp Bot - Pydantic Models
Defines data models for WhatsApp webhook payloads and internal data structures.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from datetime import datetime


# ==================== Enums ====================

class MessageType(str, Enum):
    """Types of WhatsApp messages."""
    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"
    STICKER = "sticker"
    LOCATION = "location"
    CONTACTS = "contacts"
    INTERACTIVE = "interactive"
    BUTTON = "button"
    REACTION = "reaction"


class WebhookType(str, Enum):
    """Types of webhook events."""
    MESSAGES = "messages"
    STATUSES = "statuses"


# ==================== WhatsApp Payload Models ====================

class TextMessage(BaseModel):
    """Text message content."""
    body: str


class DocumentMessage(BaseModel):
    """Document message content."""
    id: str = Field(..., description="Media ID for downloading")
    mime_type: str = Field(..., description="MIME type of the document")
    sha256: Optional[str] = None
    filename: Optional[str] = None
    caption: Optional[str] = None


class ImageMessage(BaseModel):
    """Image message content."""
    id: str
    mime_type: str
    sha256: Optional[str] = None
    caption: Optional[str] = None


class Context(BaseModel):
    """Reply context - present when message is a reply."""
    from_: Optional[str] = Field(None, alias="from")
    id: str = Field(..., description="ID of the message being replied to")


class Message(BaseModel):
    """Single WhatsApp message."""
    id: str
    from_: str = Field(..., alias="from")
    timestamp: str
    type: MessageType
    text: Optional[TextMessage] = None
    document: Optional[DocumentMessage] = None
    image: Optional[ImageMessage] = None
    context: Optional[Context] = None
    
    class Config:
        populate_by_name = True


class Contact(BaseModel):
    """Contact information from webhook."""
    wa_id: str
    profile: Optional[dict] = None


class Metadata(BaseModel):
    """Webhook metadata."""
    display_phone_number: str
    phone_number_id: str


class Value(BaseModel):
    """Webhook value containing messages."""
    messaging_product: str = "whatsapp"
    metadata: Optional[Metadata] = None
    contacts: Optional[List[Contact]] = None
    messages: Optional[List[Message]] = None


class Change(BaseModel):
    """Webhook change event."""
    value: Value
    field: str


class Entry(BaseModel):
    """Webhook entry."""
    id: str
    changes: List[Change]


class WebhookPayload(BaseModel):
    """Complete webhook payload from WhatsApp."""
    object: str
    entry: List[Entry]


# ==================== Internal Models ====================

class CommandContext(BaseModel):
    """Parsed command context from a message."""
    command: str = Field(..., description="The command text (e.g., 'simpan ke drive')")
    replied_message_id: str = Field(..., description="ID of the message being replied to")
    group_id: str = Field(..., description="Group/Chat ID")
    sender_id: str = Field(..., description="Sender's WhatsApp ID")
    message_id: str = Field(..., description="ID of the command message")
    timestamp: datetime = Field(default_factory=datetime.now)


class CachedMessage(BaseModel):
    """Message stored in cache."""
    message_id: str
    sender_id: str
    type: MessageType
    document: Optional[DocumentMessage] = None
    image: Optional[ImageMessage] = None
    text: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class FolderPrediction(BaseModel):
    """AI folder prediction result."""
    folder_id: str
    folder_name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    analysis_level: str = Field(
        default="filename_only",
        description="'filename_only' or 'content_analyzed'"
    )


class PDFContent(BaseModel):
    """Extracted PDF content."""
    text: str = ""
    first_page_image: Optional[bytes] = None
    first_page_base64: Optional[str] = None
    page_count: int = 0
    has_text: bool = False
    
    class Config:
        arbitrary_types_allowed = True


class DriveUploadResult(BaseModel):
    """Result of Google Drive upload."""
    file_id: str
    filename: str
    folder_id: str
    folder_name: str
    shareable_link: str
    web_view_link: Optional[str] = None


class ProcessingResult(BaseModel):
    """Complete result of processing a save command."""
    success: bool
    upload_result: Optional[DriveUploadResult] = None
    prediction: Optional[FolderPrediction] = None
    error_message: Optional[str] = None
