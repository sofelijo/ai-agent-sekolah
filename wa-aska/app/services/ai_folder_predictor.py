"""
ASKA WhatsApp Bot - AI Folder Predictor
Uses Gemini AI to predict the best folder for uploaded files.
Implements 2-level analysis: filename first, then content if needed.
"""

import logging
import asyncio
import re
from typing import Optional, List

from app.config import settings
from app.models.schemas import FolderPrediction, PDFContent
from app.clients.gemini_client import gemini_client, RateLimitError
from app.clients.gdrive_client import gdrive_client
from app.services.pdf_extractor import pdf_extractor

logger = logging.getLogger(__name__)

# Patterns that indicate generic/non-informative filenames
GENERIC_PATTERNS = [
    r"^document",
    r"^doc[_\-\s]?\d*",
    r"^file[_\-\s]?\d*",
    r"^scan[_\-\s]?\d*",
    r"^img[_\-\s]?\d*",
    r"^image[_\-\s]?\d*",
    r"^untitled",
    r"^new[_\-\s]?",
    r"^download",
    r"^attachment",
    r"^whatsapp[_\-\s]?",
    r"^\d+$",  # Just numbers
    r"^\d{8,}",  # Date-like (20241220)
]


class AIFolderPredictor:
    """
    Predicts target folder using AI analysis.
    
    Level 1: Analyze filename only (fast)
    Level 2: Analyze PDF content (when filename is generic)
    """
    
    def __init__(self):
        self._folders_formatted: Optional[str] = None
        self._folders_list: Optional[List[dict]] = None
    
    def is_filename_generic(self, filename: str) -> bool:
        """
        Check if filename is generic/non-informative.
        
        Args:
            filename: The file name
            
        Returns:
            True if filename is generic
        """
        # Remove extension
        name = filename.lower()
        for ext in ['.pdf', '.doc', '.docx', '.xlsx', '.xls']:
            name = name.replace(ext, '')
        
        # Replace separators with space
        name = re.sub(r'[_\-\.]', ' ', name).strip()
        
        # Check against generic patterns
        for pattern in GENERIC_PATTERNS:
            if re.match(pattern, name):
                logger.debug(f"Filename '{filename}' matched generic pattern: {pattern}")
                return True
        
        # Check if too short
        if len(name) < 5:
            return True
        
        return False
    
    async def _get_folder_list_formatted(self) -> str:
        """
        Get formatted folder list for AI prompt.
        Cached for performance.
        """
        if self._folders_formatted:
            return self._folders_formatted
        
        folders = await gdrive_client.list_folders()
        self._folders_list = folders
        
        if not folders:
            return "- Lainnya (ID: default)"
        
        lines = []
        for f in folders:
            lines.append(f"- {f['name']} (ID: {f['id']})")
        
        self._folders_formatted = "\n".join(lines)
        return self._folders_formatted
    
    def _get_default_prediction(self, reason: str = "") -> FolderPrediction:
        """Get default prediction when AI fails."""
        return FolderPrediction(
            folder_id=settings.gdrive_default_folder_id,
            folder_name="Default",
            confidence=0.0,
            reasoning=reason or "Menggunakan folder default",
            analysis_level="fallback"
        )
    
    def _parse_prediction(self, result: dict, analysis_level: str) -> FolderPrediction:
        """Parse AI result into FolderPrediction."""
        if not result:
            return self._get_default_prediction("Gagal menganalisis")
        
        # Validate folder_id exists
        folder_id = result.get('folder_id', '')
        folder_name = result.get('folder_name', 'Unknown')
        
        # Check if folder_id is valid
        if self._folders_list:
            valid_ids = [f['id'] for f in self._folders_list]
            if folder_id not in valid_ids:
                # Try to find by name
                for f in self._folders_list:
                    if f['name'].lower() == folder_name.lower():
                        folder_id = f['id']
                        break
                else:
                    # Use default
                    folder_id = settings.gdrive_default_folder_id
                    folder_name = "Default"
        
        return FolderPrediction(
            folder_id=folder_id or settings.gdrive_default_folder_id,
            folder_name=folder_name,
            confidence=float(result.get('confidence', 0.5)),
            reasoning=result.get('reasoning', 'Tidak ada alasan'),
            analysis_level=analysis_level
        )
    
    async def predict_folder(
        self,
        filename: str,
        pdf_bytes: Optional[bytes] = None
    ) -> FolderPrediction:
        """
        Predict the best folder for a file using 2-level analysis.
        
        Level 1: Analyze filename (always runs first)
        Level 2: Analyze PDF content (if filename is generic and content available)
        
        Args:
            filename: Name of the file
            pdf_bytes: Optional PDF content for deeper analysis
            
        Returns:
            FolderPrediction with folder details and confidence
        """
        try:
            folder_list = await self._get_folder_list_formatted()
            
            # ==================== LEVEL 1: Filename Analysis ====================
            is_generic = self.is_filename_generic(filename)
            
            if not is_generic:
                logger.info(f"Filename '{filename}' is informative, using Level 1 analysis")
                result = await gemini_client.predict_folder_from_filename(
                    filename=filename,
                    folder_list=folder_list
                )
                prediction = self._parse_prediction(result, "filename_only")
                
                # If confidence is high enough, use this prediction
                if prediction.confidence >= 0.6:
                    logger.info(
                        f"Level 1 prediction: {prediction.folder_name} "
                        f"(confidence: {prediction.confidence})"
                    )
                    return prediction
            
            # ==================== LEVEL 2: Content Analysis ====================
            if pdf_bytes:
                logger.info(f"Using Level 2 analysis for '{filename}'")
                
                # Extract PDF content
                pdf_content = pdf_extractor.extract_content(pdf_bytes)
                
                if pdf_content.has_text and len(pdf_content.text.strip()) >= 100:
                    # Use text analysis
                    logger.info("Using text-based analysis")
                    result = await gemini_client.predict_folder_from_text(
                        filename=filename,
                        text_content=pdf_content.text,
                        folder_list=folder_list
                    )
                elif pdf_content.first_page_base64:
                    # Use image analysis
                    logger.info("Using image-based analysis (scanned PDF)")
                    result = await gemini_client.predict_folder_from_image(
                        filename=filename,
                        image_base64=pdf_content.first_page_base64,
                        folder_list=folder_list
                    )
                else:
                    # Fallback to filename analysis
                    result = await gemini_client.predict_folder_from_filename(
                        filename=filename,
                        folder_list=folder_list
                    )
                
                prediction = self._parse_prediction(result, "content_analyzed")
                logger.info(
                    f"Level 2 prediction: {prediction.folder_name} "
                    f"(confidence: {prediction.confidence})"
                )
                return prediction
            
            # Fallback: use filename analysis anyway
            result = await gemini_client.predict_folder_from_filename(
                filename=filename,
                folder_list=folder_list
            )
            return self._parse_prediction(result, "filename_only")
            
        except RateLimitError:
            logger.warning("Gemini rate limit reached, using default folder")
            return self._get_default_prediction("Rate limit tercapai, menggunakan folder default")
        except Exception as e:
            logger.error(f"Error predicting folder: {e}")
            return self._get_default_prediction(f"Error: {str(e)[:50]}")
    
    async def predict_with_retry(
        self,
        filename: str,
        pdf_bytes: Optional[bytes] = None,
        max_retries: int = 3
    ) -> FolderPrediction:
        """
        Predict folder with retry logic for rate limits.
        
        Args:
            filename: Name of the file
            pdf_bytes: Optional PDF content
            max_retries: Maximum retry attempts
            
        Returns:
            FolderPrediction
        """
        for attempt in range(max_retries):
            try:
                return await self.predict_folder(filename, pdf_bytes)
            except RateLimitError:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                    logger.info(f"Rate limited, waiting {wait_time}s before retry")
                    await asyncio.sleep(wait_time)
                else:
                    return self._get_default_prediction(
                        "Rate limit tercapai setelah retry, menggunakan folder default"
                    )
        
        return self._get_default_prediction("Unexpected error")
    
    def invalidate_cache(self):
        """Invalidate folder cache."""
        self._folders_formatted = None
        self._folders_list = None
        gdrive_client.invalidate_folder_cache()


# Global predictor instance
ai_predictor = AIFolderPredictor()
