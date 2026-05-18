"""
ASKA WhatsApp Bot - Main Application
FastAPI entry point with webhook routes and lifecycle management.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.webhook import router as webhook_router
from app.services.message_cache import message_cache

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("🚀 Starting ASKA WhatsApp Bot...")
    logger.info(f"📱 WhatsApp Phone Number ID: {settings.whatsapp_phone_number_id}")
    logger.info(f"📁 Default Drive Folder: {settings.gdrive_default_folder_id}")
    
    # Start background cache cleanup task
    import asyncio
    cleanup_task = asyncio.create_task(message_cache.cleanup_expired())
    
    yield
    
    # Shutdown
    logger.info("👋 Shutting down ASKA WhatsApp Bot...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


# Create FastAPI application
app = FastAPI(
    title="ASKA WhatsApp Bot",
    description="AI-powered WhatsApp bot for saving PDFs to Google Drive",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include webhook router
app.include_router(webhook_router, prefix="/webhook", tags=["webhook"])


@app.get("/", tags=["health"])
async def root():
    """Root endpoint - health check."""
    return {
        "status": "ok",
        "service": "ASKA WhatsApp Bot",
        "version": "1.0.0"
    }


@app.get("/health", tags=["health"])
async def health_check():
    """Detailed health check endpoint."""
    return {
        "status": "healthy",
        "cache_size": len(message_cache._cache),
        "debug_mode": settings.debug
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
