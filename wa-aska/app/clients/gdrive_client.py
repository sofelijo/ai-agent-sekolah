"""
ASKA WhatsApp Bot - Google Drive API Client
Handles authentication and file operations with Google Drive.
"""

import logging
import os
from typing import Optional, List
from io import BytesIO

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError

from app.config import settings
from app.models.schemas import DriveUploadResult

logger = logging.getLogger(__name__)

# Required scopes for Google Drive
SCOPES = [
    'https://www.googleapis.com/auth/drive.file',  # Create/modify files created by app
    'https://www.googleapis.com/auth/drive.metadata.readonly'  # Read folder structure
]


class GoogleDriveError(Exception):
    """Custom exception for Google Drive errors."""
    pass


class GoogleDriveClient:
    """
    Client for Google Drive API.
    Handles authentication and file upload operations.
    """
    
    def __init__(self):
        self.credentials_path = settings.gdrive_credentials_path
        self.token_path = settings.gdrive_token_path
        self.default_folder_id = settings.gdrive_default_folder_id
        self._service = None
        self._folders_cache = None
    
    def _get_credentials(self) -> Credentials:
        """
        Get or refresh OAuth credentials.
        
        Returns:
            Valid Google OAuth credentials
            
        Raises:
            GoogleDriveError: If authentication fails
        """
        creds = None
        
        # Load existing token
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception as e:
                logger.warning(f"Failed to load token: {e}")
        
        # Refresh or get new token
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning(f"Failed to refresh token: {e}")
                    creds = None
            
            if not creds:
                if not os.path.exists(self.credentials_path):
                    raise GoogleDriveError(
                        f"Credentials file not found: {self.credentials_path}. "
                        "Please download OAuth credentials from Google Cloud Console."
                    )
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save token for future use
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
        
        return creds
    
    @property
    def service(self):
        """
        Get Drive service, initializing if needed.
        """
        if self._service is None:
            creds = self._get_credentials()
            self._service = build('drive', 'v3', credentials=creds)
        return self._service
    
    async def list_folders(self, parent_id: Optional[str] = None) -> List[dict]:
        """
        List all folders in a parent directory.
        
        Args:
            parent_id: Parent folder ID (uses default if None)
            
        Returns:
            List of folder dicts with 'id' and 'name'
        """
        if self._folders_cache is not None:
            return self._folders_cache
        
        try:
            query = "mimeType='application/vnd.google-apps.folder' and trashed=false"
            if parent_id:
                query += f" and '{parent_id}' in parents"
            
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, parents)',
                pageSize=100
            ).execute()
            
            folders = results.get('files', [])
            
            # Cache the results
            self._folders_cache = folders
            
            logger.info(f"Found {len(folders)} folders")
            return folders
            
        except HttpError as e:
            raise GoogleDriveError(f"Failed to list folders: {e}")
    
    def invalidate_folder_cache(self):
        """Invalidate the folder cache."""
        self._folders_cache = None
    
    async def upload_file(
        self,
        file_content: bytes,
        filename: str,
        folder_id: Optional[str] = None,
        mime_type: str = 'application/pdf'
    ) -> DriveUploadResult:
        """
        Upload a file to Google Drive.
        
        Args:
            file_content: Binary content of the file
            filename: Name for the uploaded file
            folder_id: Folder ID to upload to (uses default if None)
            mime_type: MIME type of the file
            
        Returns:
            DriveUploadResult with file details and shareable link
            
        Raises:
            GoogleDriveError: If upload fails
        """
        target_folder_id = folder_id or self.default_folder_id
        
        try:
            # Get folder name for result
            folder_name = "Unknown"
            try:
                folder_meta = self.service.files().get(
                    fileId=target_folder_id,
                    fields='name'
                ).execute()
                folder_name = folder_meta.get('name', 'Unknown')
            except Exception:
                pass
            
            # Prepare file metadata
            file_metadata = {
                'name': filename,
                'parents': [target_folder_id]
            }
            
            # Create media upload
            media = MediaIoBaseUpload(
                BytesIO(file_content),
                mimetype=mime_type,
                resumable=True
            )
            
            # Upload file
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink, webContentLink'
            ).execute()
            
            file_id = file.get('id')
            
            # Make file accessible via link
            try:
                self.service.permissions().create(
                    fileId=file_id,
                    body={
                        'type': 'anyone',
                        'role': 'reader'
                    }
                ).execute()
            except Exception as e:
                logger.warning(f"Failed to set permissions: {e}")
            
            logger.info(f"Uploaded {filename} to folder {folder_name}")
            
            return DriveUploadResult(
                file_id=file_id,
                filename=filename,
                folder_id=target_folder_id,
                folder_name=folder_name,
                shareable_link=file.get('webViewLink', ''),
                web_view_link=file.get('webViewLink')
            )
            
        except HttpError as e:
            raise GoogleDriveError(f"Failed to upload file: {e}")
    
    async def get_folder_by_name(self, name: str) -> Optional[dict]:
        """
        Find a folder by name.
        
        Args:
            name: Folder name to search for
            
        Returns:
            Folder dict if found, None otherwise
        """
        folders = await self.list_folders()
        for folder in folders:
            if folder['name'].lower() == name.lower():
                return folder
        return None


# Global client instance
gdrive_client = GoogleDriveClient()
