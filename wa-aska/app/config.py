"""
ASKA WhatsApp Bot - Configuration Module
Manages all environment variables and settings using Pydantic Settings.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    """
    
    # WhatsApp Cloud API
    whatsapp_access_token: str = Field(..., alias="WA_ASKA_ACCESS_TOKEN", description="WhatsApp Cloud API access token")
    whatsapp_phone_number_id: str = Field(..., alias="WA_ASKA_PHONE_NUMBER_ID", description="WhatsApp phone number ID")
    whatsapp_verify_token: str = Field(..., alias="WA_ASKA_VERIFY_TOKEN", description="Webhook verification token")
    whatsapp_api_version: str = Field(default="v17.0", alias="WA_ASKA_API_VERSION", description="WhatsApp API version")
    
    # Google Drive
    gdrive_credentials_path: str = Field(
        default="/Users/ainunfajar/BOT_TELE/ai-agent-sekolah/wa-aska/credentials/credentials.json",
        alias="WA_ASKA_GDRIVE_CREDENTIALS_PATH",
        description="Path to Google OAuth credentials file"
    )
    gdrive_token_path: str = Field(
        default="/Users/ainunfajar/BOT_TELE/ai-agent-sekolah/wa-aska/credentials/token.json",
        alias="WA_ASKA_GDRIVE_TOKEN_PATH",
        description="Path to Google OAuth token file"
    )
    gdrive_default_folder_id: str = Field(..., alias="WA_ASKA_GDRIVE_FOLDER_ID", description="Default Google Drive folder ID")
    
    # Gemini AI
    gemini_api_key: str = Field(..., alias="WA_ASKA_GEMINI_API_KEY", description="Google Gemini API key")
    
    # PDF Processing
    pdf_max_text_chars: int = Field(default=2000, alias="WA_ASKA_PDF_MAX_TEXT", description="Max characters to extract from PDF")
    pdf_render_dpi: int = Field(default=150, alias="WA_ASKA_PDF_DPI", description="DPI for PDF to image rendering")
    
    # Server
    host: str = Field(default="0.0.0.0", alias="WA_ASKA_HOST", description="Server host")
    port: int = Field(default=8000, alias="WA_ASKA_PORT", description="Server port")
    debug: bool = Field(default=True, alias="WA_ASKA_DEBUG", description="Debug mode")
    
    # Message Cache
    cache_ttl_hours: int = Field(default=24, alias="WA_ASKA_CACHE_TTL", description="Message cache TTL in hours")
    
    @property
    def whatsapp_api_base_url(self) -> str:
        """Base URL for WhatsApp Cloud API."""
        return f"https://graph.facebook.com/{self.whatsapp_api_version}"
    
    @property
    def whatsapp_messages_url(self) -> str:
        """URL for sending WhatsApp messages."""
        return f"{self.whatsapp_api_base_url}/{self.whatsapp_phone_number_id}/messages"
    
    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        populate_by_name = True
        extra = "ignore"  # PENTING: Abaikan variabel lain di .env (seperti config DB, Twitter, dll)


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache for performance - settings are loaded once.
    """
    return Settings()


# Convenience export
settings = get_settings()
