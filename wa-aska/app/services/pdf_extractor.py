"""
ASKA WhatsApp Bot - PDF Extractor
Extracts text and images from PDF files for AI analysis.
"""

import logging
import base64
from io import BytesIO

import fitz  # PyMuPDF

from app.config import settings
from app.models.schemas import PDFContent

logger = logging.getLogger(__name__)


class PDFExtractor:
    """
    Extract content from PDF files for AI analysis.
    
    Supports:
    - Text extraction from text-based PDFs
    - Image rendering for scanned/image PDFs
    """
    
    def __init__(
        self,
        max_text_chars: int = None,
        render_dpi: int = None
    ):
        self.max_text_chars = max_text_chars or settings.pdf_max_text_chars
        self.render_dpi = render_dpi or settings.pdf_render_dpi
    
    def extract_content(self, pdf_bytes: bytes) -> PDFContent:
        """
        Extract text and image from the first page of a PDF.
        
        Args:
            pdf_bytes: Binary content of the PDF file
            
        Returns:
            PDFContent with extracted text and/or image
        """
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            
            try:
                page_count = len(doc)
                
                if page_count == 0:
                    logger.warning("PDF has no pages")
                    return PDFContent(
                        text="",
                        first_page_image=None,
                        first_page_base64=None,
                        page_count=0,
                        has_text=False
                    )
                
                # Get first page
                first_page = doc[0]
                
                # 1. Extract text
                text = first_page.get_text("text")
                text = text.strip()
                
                # Truncate if too long
                if len(text) > self.max_text_chars:
                    text = text[:self.max_text_chars]
                
                # Check if meaningful text exists
                # (some scanned PDFs have just whitespace or OCR artifacts)
                has_text = len(text.strip()) >= 50
                
                # 2. Render page to image
                # Use matrix to set DPI (default is 72 DPI)
                zoom = self.render_dpi / 72
                mat = fitz.Matrix(zoom, zoom)
                pix = first_page.get_pixmap(matrix=mat)
                
                # Convert to PNG bytes
                img_bytes = pix.tobytes("png")
                
                # Convert to base64 for Gemini API
                img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                
                logger.info(
                    f"Extracted PDF: {page_count} pages, "
                    f"{len(text)} chars text, "
                    f"has_text={has_text}"
                )
                
                return PDFContent(
                    text=text,
                    first_page_image=img_bytes,
                    first_page_base64=img_base64,
                    page_count=page_count,
                    has_text=has_text
                )
                
            finally:
                doc.close()
                
        except Exception as e:
            logger.error(f"Error extracting PDF content: {e}")
            return PDFContent(
                text="",
                first_page_image=None,
                first_page_base64=None,
                page_count=0,
                has_text=False
            )
    
    def should_use_image_analysis(self, pdf_content: PDFContent) -> bool:
        """
        Determine if image analysis should be used.
        
        Image analysis is preferred when:
        - PDF has no text (likely a scanned document)
        - PDF has very little text (less than 100 chars)
        
        Args:
            pdf_content: Extracted PDF content
            
        Returns:
            True if image analysis should be used
        """
        if not pdf_content.has_text:
            return True
        
        if len(pdf_content.text.strip()) < 100:
            return True
        
        return False
    
    def extract_text_only(self, pdf_bytes: bytes) -> str:
        """
        Extract only text from PDF (faster, for quick checks).
        
        Args:
            pdf_bytes: Binary content of the PDF
            
        Returns:
            Extracted text
        """
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            try:
                if len(doc) == 0:
                    return ""
                
                text = doc[0].get_text("text")
                return text[:self.max_text_chars] if text else ""
            finally:
                doc.close()
        except Exception as e:
            logger.error(f"Error extracting text: {e}")
            return ""


# Global extractor instance
pdf_extractor = PDFExtractor()
