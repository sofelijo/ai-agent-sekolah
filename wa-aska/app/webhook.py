"""
ASKA WhatsApp Bot - Webhook Handler
Handles incoming webhook requests from WhatsApp Cloud API.
"""

import logging
from fastapi import APIRouter, Request, Response, BackgroundTasks, Query, HTTPException

from app.config import settings
from app.services.message_parser import extract_messages, parse_command
from app.services.message_cache import message_cache
from app.services.file_handler import file_handler

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    """
    Webhook verification endpoint for WhatsApp Cloud API.
    
    Meta sends a GET request with these query parameters to verify
    the webhook URL during setup.
    
    Args:
        hub_mode: Should be "subscribe"
        hub_verify_token: Token that must match our configured token
        hub_challenge: Challenge string to return for verification
        
    Returns:
        The challenge string if verification succeeds
        
    Raises:
        HTTPException: If verification fails
    """
    logger.info(f"Webhook verification request: mode={hub_mode}")
    
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("Webhook verified successfully")
        return Response(content=hub_challenge, media_type="text/plain")
    
    logger.warning(f"Webhook verification failed: token mismatch")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Receive webhook events from WhatsApp Cloud API.
    
    This endpoint receives all incoming messages and status updates.
    Processing is done in background tasks to ensure quick response.
    
    Args:
        request: The incoming request
        background_tasks: FastAPI background tasks
        
    Returns:
        Acknowledgment response
    """
    try:
        payload = await request.json()
        logger.debug(f"Received webhook payload: {payload}")
        
        # Extract messages from payload
        messages = extract_messages(payload)
        
        if not messages:
            logger.debug("No messages in payload")
            return {"status": "ok"}
        
        logger.info(f"Processing {len(messages)} messages")
        
        for message in messages:
            message_id = message.get("id", "unknown")
            message_type = message.get("type", "unknown")
            
            # Cache document messages for later lookup
            if message_type in ["document", "image"]:
                message_cache.store_from_webhook(message)
                logger.info(f"Cached {message_type} message: {message_id}")
            
            # Check for save command
            command = parse_command(message)
            if command:
                logger.info(f"Detected save command, processing in background")
                # Process command in background to return quickly
                background_tasks.add_task(
                    process_save_command,
                    command
                )
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        # Always return 200 to prevent retries from WhatsApp
        return {"status": "ok", "error": str(e)}


async def process_save_command(command):
    """
    Background task to process a save command.
    
    Args:
        command: The CommandContext to process
    """
    try:
        logger.info(f"Processing save command: {command.message_id}")
        result = await file_handler.handle_save_command(command)
        
        if result.success:
            logger.info(
                f"Successfully processed command {command.message_id}: "
                f"uploaded to {result.prediction.folder_name}"
            )
        else:
            logger.warning(
                f"Failed to process command {command.message_id}: "
                f"{result.error_message}"
            )
            
    except Exception as e:
        logger.error(f"Error processing command {command.message_id}: {e}")
