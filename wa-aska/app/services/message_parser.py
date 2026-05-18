"""
ASKA WhatsApp Bot - Message Parser
Parses incoming webhook payloads and detects save commands.
"""

import logging
from typing import Optional, List

from app.models.schemas import (
    WebhookPayload,
    Message,
    CommandContext,
    MessageType
)

logger = logging.getLogger(__name__)

# Valid commands that trigger save to drive
VALID_COMMANDS = [
    "simpan ke drive",
    "simpan di drive",
    "save to drive",
    "save",
    "/save",
    "/simpan"
]


def extract_messages(payload: dict) -> List[dict]:
    """
    Extract messages from webhook payload.
    
    Args:
        payload: Raw webhook payload dict
        
    Returns:
        List of message dicts
    """
    messages = []
    
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                msgs = value.get("messages", [])
                messages.extend(msgs)
    except Exception as e:
        logger.error(f"Error extracting messages: {e}")
    
    return messages


def is_valid_command(text: str) -> bool:
    """
    Check if text is a valid save command.
    
    Args:
        text: Message text
        
    Returns:
        True if text is a valid command
    """
    normalized = text.lower().strip()
    return normalized in VALID_COMMANDS


def parse_command(message: dict) -> Optional[CommandContext]:
    """
    Parse a message to detect if it's a save command.
    
    Args:
        message: Message dict from webhook
        
    Returns:
        CommandContext if valid command detected, None otherwise
    """
    try:
        # 1. Must be a text message
        if message.get("type") != "text":
            return None
        
        # 2. Must have context (be a reply)
        context = message.get("context")
        if not context:
            logger.debug("Message is not a reply, skipping")
            return None
        
        replied_message_id = context.get("id")
        if not replied_message_id:
            return None
        
        # 3. Must be a valid command
        text_body = message.get("text", {}).get("body", "")
        if not is_valid_command(text_body):
            return None
        
        # Build command context
        command = CommandContext(
            command=text_body.lower().strip(),
            replied_message_id=replied_message_id,
            group_id=message.get("from", ""),
            sender_id=message.get("from", ""),
            message_id=message.get("id", "")
        )
        
        logger.info(f"Detected save command from {command.sender_id}")
        return command
        
    except Exception as e:
        logger.error(f"Error parsing command: {e}")
        return None


def parse_webhook_payload(payload: dict) -> tuple[List[dict], Optional[CommandContext]]:
    """
    Parse complete webhook payload.
    
    Args:
        payload: Raw webhook payload
        
    Returns:
        Tuple of (all messages, detected command or None)
    """
    messages = extract_messages(payload)
    command = None
    
    for message in messages:
        cmd = parse_command(message)
        if cmd:
            command = cmd
            break  # Only process first command
    
    return messages, command


def is_document_message(message: dict) -> bool:
    """Check if message is a document."""
    return message.get("type") == "document"


def is_pdf_document(message: dict) -> bool:
    """Check if message is a PDF document."""
    if not is_document_message(message):
        return False
    
    doc = message.get("document", {})
    mime_type = doc.get("mime_type", "")
    
    return mime_type == "application/pdf"


def get_document_info(message: dict) -> Optional[dict]:
    """
    Extract document info from message.
    
    Returns:
        Dict with id, mime_type, filename, or None
    """
    if not is_document_message(message):
        return None
    
    doc = message.get("document", {})
    return {
        "id": doc.get("id"),
        "mime_type": doc.get("mime_type"),
        "filename": doc.get("filename", "document.pdf"),
        "sha256": doc.get("sha256")
    }
