"""
ASKA WhatsApp Bot - File Handler
Orchestrates the complete flow from command detection to upload confirmation.
"""

import logging
from typing import Optional

from app.config import settings
from app.models.schemas import (
    CommandContext,
    CachedMessage,
    ProcessingResult,
    MessageType
)
from app.clients.whatsapp_client import (
    whatsapp_client,
    MediaExpiredError,
    WhatsAppClientError
)
from app.clients.gdrive_client import gdrive_client, GoogleDriveError
from app.services.message_cache import message_cache
from app.services.ai_folder_predictor import ai_predictor

logger = logging.getLogger(__name__)


class FileHandler:
    """
    Orchestrates the complete save-to-drive flow.
    
    1. Validate command and get original message
    2. Download PDF from WhatsApp
    3. Use AI to predict target folder
    4. Upload to Google Drive
    5. Send confirmation message
    """
    
    async def handle_save_command(
        self,
        command: CommandContext
    ) -> ProcessingResult:
        """
        Handle a save-to-drive command.
        
        Args:
            command: Parsed command context
            
        Returns:
            ProcessingResult with success status and details
        """
        logger.info(f"Processing save command from {command.sender_id}")
        
        # 1. Get original message from cache
        original_message = message_cache.get(command.replied_message_id)
        
        if not original_message:
            error_msg = "❌ Pesan tidak ditemukan. Mungkin sudah lebih dari 24 jam atau bukan dokumen."
            await self._send_error_reply(command, error_msg)
            return ProcessingResult(
                success=False,
                error_message="Original message not found in cache"
            )
        
        # 2. Validate it's a PDF document
        if original_message.type != MessageType.DOCUMENT:
            error_msg = "❌ Pesan yang di-reply bukan dokumen. Silakan reply ke file PDF."
            await self._send_error_reply(command, error_msg)
            return ProcessingResult(
                success=False,
                error_message="Replied message is not a document"
            )
        
        if not original_message.document:
            error_msg = "❌ Tidak dapat membaca informasi dokumen."
            await self._send_error_reply(command, error_msg)
            return ProcessingResult(
                success=False,
                error_message="Document info missing"
            )
        
        # Check MIME type
        mime_type = original_message.document.mime_type
        if mime_type != "application/pdf":
            error_msg = f"❌ File harus berformat PDF. Format saat ini: {mime_type}"
            await self._send_error_reply(command, error_msg)
            return ProcessingResult(
                success=False,
                error_message=f"Invalid MIME type: {mime_type}"
            )
        
        # 3. Download file from WhatsApp
        media_id = original_message.document.id
        filename = original_message.document.filename or "document.pdf"
        
        try:
            logger.info(f"Downloading media {media_id}")
            file_content = await whatsapp_client.download_media(media_id)
            logger.info(f"Downloaded {len(file_content)} bytes")
            
        except MediaExpiredError:
            error_msg = "❌ Media sudah expired. Silakan kirim ulang file-nya dan coba lagi."
            await self._send_error_reply(command, error_msg)
            return ProcessingResult(
                success=False,
                error_message="Media URL expired"
            )
        except WhatsAppClientError as e:
            error_msg = "❌ Gagal mengunduh file dari WhatsApp. Silakan coba lagi."
            await self._send_error_reply(command, error_msg)
            return ProcessingResult(
                success=False,
                error_message=f"Download failed: {e}"
            )
        
        # 4. Use AI to predict target folder
        try:
            logger.info(f"Predicting folder for '{filename}'")
            prediction = await ai_predictor.predict_with_retry(
                filename=filename,
                pdf_bytes=file_content
            )
            logger.info(
                f"Predicted folder: {prediction.folder_name} "
                f"(confidence: {prediction.confidence})"
            )
            
        except Exception as e:
            logger.error(f"AI prediction failed: {e}")
            # Use default folder on AI failure
            from app.models.schemas import FolderPrediction
            prediction = FolderPrediction(
                folder_id=settings.gdrive_default_folder_id,
                folder_name="Default",
                confidence=0.0,
                reasoning="AI prediction failed, using default folder",
                analysis_level="fallback"
            )
        
        # 5. Upload to Google Drive
        try:
            logger.info(f"Uploading to folder {prediction.folder_id}")
            upload_result = await gdrive_client.upload_file(
                file_content=file_content,
                filename=filename,
                folder_id=prediction.folder_id
            )
            logger.info(f"Uploaded successfully: {upload_result.file_id}")
            
        except GoogleDriveError as e:
            error_msg = "❌ Gagal mengupload ke Google Drive. Silakan coba lagi."
            await self._send_error_reply(command, error_msg)
            return ProcessingResult(
                success=False,
                error_message=f"Upload failed: {e}"
            )
        
        # 6. Send success confirmation
        await self._send_success_reply(
            command=command,
            filename=filename,
            prediction=prediction,
            shareable_link=upload_result.shareable_link
        )
        
        return ProcessingResult(
            success=True,
            upload_result=upload_result,
            prediction=prediction
        )
    
    async def _send_error_reply(
        self,
        command: CommandContext,
        message: str
    ) -> None:
        """Send error reply message."""
        try:
            await whatsapp_client.send_reply(
                to=command.group_id,
                reply_to_message_id=command.message_id,
                text=message
            )
        except Exception as e:
            logger.error(f"Failed to send error reply: {e}")
    
    async def _send_success_reply(
        self,
        command: CommandContext,
        filename: str,
        prediction,
        shareable_link: str
    ) -> None:
        """Send success confirmation message."""
        try:
            # Confidence indicator
            if prediction.confidence > 0.7:
                confidence_emoji = "🟢"
            elif prediction.confidence > 0.4:
                confidence_emoji = "🟡"
            else:
                confidence_emoji = "🔴"
            
            # Analysis level indicator
            if prediction.analysis_level == "content_analyzed":
                analysis_note = "📖 Dianalisis dari isi dokumen"
            elif prediction.analysis_level == "filename_only":
                analysis_note = "📝 Dianalisis dari nama file"
            else:
                analysis_note = "⚙️ Folder default"
            
            message = (
                f"✅ File berhasil disimpan ke Google Drive!\n\n"
                f"📄 *Nama:* {filename}\n"
                f"📁 *Folder:* {prediction.folder_name} {confidence_emoji}\n"
                f"💡 *Alasan:* {prediction.reasoning}\n"
                f"{analysis_note}\n"
                f"🔗 *Link:* {shareable_link}"
            )
            
            await whatsapp_client.send_reply(
                to=command.group_id,
                reply_to_message_id=command.message_id,
                text=message
            )
            
        except Exception as e:
            logger.error(f"Failed to send success reply: {e}")


# Global handler instance
file_handler = FileHandler()
