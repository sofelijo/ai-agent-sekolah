"""
ASKA WhatsApp Bot - Gemini AI Client
Handles communication with Google Gemini API for AI predictions.
"""

import logging
import json
import re
import asyncio
from typing import Optional, List, Union
from PIL import Image
from io import BytesIO
import base64

import google.generativeai as genai

from app.config import settings

logger = logging.getLogger(__name__)


class GeminiError(Exception):
    """Custom exception for Gemini API errors."""
    pass


class RateLimitError(GeminiError):
    """Exception when rate limit is reached."""
    pass


class GeminiClient:
    """
    Client for Google Gemini API.
    Handles text and multimodal (image) generation.
    """
    
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Generation config for consistent JSON output
        self.generation_config = genai.GenerationConfig(
            temperature=0.3,  # Lower temperature for more consistent results
            top_p=0.95,
            max_output_tokens=1024,
        )
    
    async def generate_text(self, prompt: str) -> str:
        """
        Generate text from a prompt.
        
        Args:
            prompt: The text prompt
            
        Returns:
            Generated text response
            
        Raises:
            GeminiError: If generation fails
            RateLimitError: If rate limit is exceeded
        """
        try:
            response = await self.model.generate_content_async(
                prompt,
                generation_config=self.generation_config
            )
            return response.text
            
        except Exception as e:
            error_str = str(e).lower()
            if 'quota' in error_str or 'rate' in error_str or '429' in error_str:
                raise RateLimitError(f"Gemini rate limit exceeded: {e}")
            raise GeminiError(f"Gemini generation failed: {e}")
    
    async def generate_with_image(
        self,
        prompt: str,
        image_data: Union[bytes, str]
    ) -> str:
        """
        Generate text from a prompt with an image (multimodal).
        
        Args:
            prompt: The text prompt
            image_data: Image bytes or base64 string
            
        Returns:
            Generated text response
            
        Raises:
            GeminiError: If generation fails
        """
        try:
            # Convert to PIL Image
            if isinstance(image_data, str):
                # Base64 string
                img_bytes = base64.b64decode(image_data)
            else:
                img_bytes = image_data
            
            img = Image.open(BytesIO(img_bytes))
            
            # Generate with image
            response = await self.model.generate_content_async(
                [prompt, img],
                generation_config=self.generation_config
            )
            return response.text
            
        except Exception as e:
            error_str = str(e).lower()
            if 'quota' in error_str or 'rate' in error_str or '429' in error_str:
                raise RateLimitError(f"Gemini rate limit exceeded: {e}")
            raise GeminiError(f"Gemini multimodal generation failed: {e}")
    
    def parse_json_response(self, text: str) -> dict:
        """
        Parse JSON from Gemini response text.
        Handles cases where JSON is embedded in markdown code blocks.
        
        Args:
            text: Response text from Gemini
            
        Returns:
            Parsed JSON as dict
        """
        # Try to find JSON in code blocks first
        code_block_match = re.search(r'```(?:json)?\s*(\{[^`]*\})\s*```', text, re.DOTALL)
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try to find raw JSON object
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        # Fallback - try parsing entire response
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON from response: {text[:200]}...")
            return {}
    
    async def predict_folder_from_filename(
        self,
        filename: str,
        folder_list: str
    ) -> dict:
        """
        Predict folder based on filename only.
        
        Args:
            filename: Name of the file
            folder_list: Formatted list of available folders
            
        Returns:
            Prediction dict with folder_id, folder_name, confidence, reasoning
        """
        prompt = f"""
Kamu adalah asisten AI yang membantu mengorganisir file di Google Drive.

Tugas: Tentukan folder terbaik berdasarkan NAMA FILE.

Nama File: "{filename}"

Daftar Folder yang Tersedia:
{folder_list}

Aturan:
1. Analisis nama file untuk menentukan kategori
2. Cocokkan dengan folder yang paling relevan
3. Berikan confidence score (0.0-1.0) berdasarkan seberapa yakin prediksimu

Jawab HANYA dalam format JSON (tanpa teks lain):
{{
    "folder_id": "ID folder yang dipilih",
    "folder_name": "Nama folder",
    "confidence": 0.8,
    "reasoning": "Alasan singkat dalam Bahasa Indonesia"
}}
"""
        response = await self.generate_text(prompt)
        return self.parse_json_response(response)
    
    async def predict_folder_from_text(
        self,
        filename: str,
        text_content: str,
        folder_list: str
    ) -> dict:
        """
        Predict folder based on PDF text content.
        
        Args:
            filename: Name of the file
            text_content: Extracted text from PDF
            folder_list: Formatted list of available folders
            
        Returns:
            Prediction dict
        """
        # Truncate text if too long
        max_chars = settings.pdf_max_text_chars
        if len(text_content) > max_chars:
            text_content = text_content[:max_chars] + "..."
        
        prompt = f"""
Kamu adalah asisten AI yang membantu mengorganisir file di Google Drive.

Tugas: Tentukan folder terbaik berdasarkan ISI DOKUMEN.

Nama File: "{filename}"

Isi Halaman Pertama:
---
{text_content}
---

Daftar Folder yang Tersedia:
{folder_list}

Analisis isi dokumen dan tentukan kategori yang paling sesuai.
Jawab HANYA dalam format JSON (tanpa teks lain):
{{
    "folder_id": "ID folder yang dipilih",
    "folder_name": "Nama folder",
    "confidence": 0.8,
    "reasoning": "Alasan berdasarkan isi dokumen dalam Bahasa Indonesia"
}}
"""
        response = await self.generate_text(prompt)
        return self.parse_json_response(response)
    
    async def predict_folder_from_image(
        self,
        filename: str,
        image_base64: str,
        folder_list: str
    ) -> dict:
        """
        Predict folder based on PDF page image (for scanned documents).
        
        Args:
            filename: Name of the file
            image_base64: Base64 encoded image of first page
            folder_list: Formatted list of available folders
            
        Returns:
            Prediction dict
        """
        prompt = f"""
Kamu adalah asisten AI yang membantu mengorganisir file di Google Drive.

Tugas: Analisis gambar halaman pertama PDF ini dan tentukan folder terbaik.

Nama File: "{filename}"

Daftar Folder yang Tersedia:
{folder_list}

Perhatikan:
- Jenis dokumen (surat, invoice, laporan, formulir, dll)
- Logo atau header yang terlihat
- Format dan layout dokumen

Jawab HANYA dalam format JSON (tanpa teks lain):
{{
    "folder_id": "ID folder yang dipilih",
    "folder_name": "Nama folder",
    "confidence": 0.8,
    "reasoning": "Alasan berdasarkan analisis visual dalam Bahasa Indonesia"
}}
"""
        response = await self.generate_with_image(prompt, image_base64)
        return self.parse_json_response(response)


# Global client instance
gemini_client = GeminiClient()
