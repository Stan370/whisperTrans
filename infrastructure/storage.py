import os
import boto3
import tempfile
from typing import Optional, BinaryIO, Dict, Any
from pathlib import Path
from config import settings
from utils.logger import get_logger

logger = get_logger("storage")

class StorageManager:
    """File storage manager supporting local and S3 storage."""
    
    def __init__(self):
        self.s3_client = None
        self.settings = settings
        self._setup_storage()
    
    def _setup_storage(self):
        """Setup storage backend based on configuration."""
        if self.settings.s3_access_key and self.settings.s3_secret_key:
            try:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=self.settings.s3_access_key,
                    aws_secret_access_key=self.settings.s3_secret_key,
                    region_name=self.settings.s3_region
                )
                logger.info("S3 storage configured successfully")
            except Exception as e:
                logger.error(f"Failed to configure S3: {e}")
                self.s3_client = None
        
        # Ensure local directories exist
        os.makedirs(self.settings.upload_dir, exist_ok=True)
        os.makedirs(self.settings.result_dir, exist_ok=True)
        logger.info("Local storage directories created")
    
    def is_s3_available(self) -> bool:
        """Check if S3 storage is available."""
        return self.s3_client is not None
    
    def upload_file(self, file_path: str, key: str, metadata: Optional[Dict[str, str]] = None) -> bool:
        """Upload file to storage."""
        try:
            if self.is_s3_available():
                return self._upload_to_s3(file_path, key, metadata)
            else:
                return self._upload_to_local(file_path, key)
        except Exception as e:
            logger.error(f"Failed to upload file {file_path}: {e}")
            return False
    
    def _upload_to_s3(self, file_path: str, key: str, metadata: Optional[Dict[str, str]] = None) -> bool:
        """Upload file to S3."""
        try:
            self.s3_client.upload_file(
                file_path,
                self.settings.s3_bucket,
                key,
                ExtraArgs={'Metadata': metadata} if metadata else {}
            )
            logger.info(f"File uploaded to S3: {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload to S3: {e}")
            return False
    
    def _upload_to_local(self, file_path: str, key: str) -> bool:
        """Upload file to local storage."""
        try:
            dest_path = os.path.join(self.settings.upload_dir, key)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            
            with open(file_path, "rb") as src, open(dest_path, "wb") as dst:
                dst.write(src.read())
            
            logger.info(f"File uploaded to local storage: {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload to local storage: {e}")
            return False
    
    def download_file(self, key: str, dest_path: Optional[str] = None) -> Optional[str]:
        """Download file from storage."""
        try:
            if self.is_s3_available():
                return self._download_from_s3(key, dest_path)
            else:
                return self._download_from_local(key, dest_path)
        except Exception as e:
            logger.error(f"Failed to download file {key}: {e}")
            return None
    
    def _download_from_s3(self, key: str, dest_path: Optional[str] = None) -> Optional[str]:
        """Download file from S3."""
        try:
            if not dest_path:
                dest_path = os.path.join(self.settings.upload_dir, os.path.basename(key))
            
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            self.s3_client.download_file(self.settings.s3_bucket, key, dest_path)
            
            logger.info(f"File downloaded from S3: {key}")
            return dest_path
        except Exception as e:
            logger.error(f"Failed to download from S3: {e}")
            return None
    
    def _download_from_local(self, key: str, dest_path: Optional[str] = None) -> Optional[str]:
        """Download file from local storage."""
        try:
            src_path = os.path.join(self.settings.upload_dir, key)
            if not os.path.exists(src_path):
                logger.error(f"File not found in local storage: {key}")
                return None
            
            if not dest_path:
                dest_path = src_path
            
            if src_path != dest_path:
                with open(src_path, "rb") as src, open(dest_path, "wb") as dst:
                    dst.write(src.read())
            
            logger.info(f"File downloaded from local storage: {key}")
            return dest_path
        except Exception as e:
            logger.error(f"Failed to download from local storage: {e}")
            return None
    
    def delete_file(self, key: str) -> bool:
        """Delete file from storage."""
        try:
            if self.is_s3_available():
                return self._delete_from_s3(key)
            else:
                return self._delete_from_local(key)
        except Exception as e:
            logger.error(f"Failed to delete file {key}: {e}")
            return False
    
    def _delete_from_s3(self, key: str) -> bool:
        """Delete file from S3."""
        try:
            self.s3_client.delete_object(Bucket=self.settings.s3_bucket, Key=key)
            logger.info(f"File deleted from S3: {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete from S3: {e}")
            return False
    
    def _delete_from_local(self, key: str) -> bool:
        """Delete file from local storage."""
        try:
            file_path = os.path.join(self.settings.upload_dir, key)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"File deleted from local storage: {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete from local storage: {e}")
            return False
    
    def file_exists(self, key: str) -> bool:
        """Check if file exists in storage."""
        try:
            if self.is_s3_available():
                return self._exists_in_s3(key)
            else:
                return self._exists_in_local(key)
        except Exception as e:
            logger.error(f"Failed to check file existence {key}: {e}")
            return False
    
    def _exists_in_s3(self, key: str) -> bool:
        """Check if file exists in S3."""
        try:
            self.s3_client.head_object(Bucket=self.settings.s3_bucket, Key=key)
            return True
        except Exception:
            return False
    
    def _exists_in_local(self, key: str) -> bool:
        """Check if file exists in local storage."""
        file_path = os.path.join(self.settings.upload_dir, key)
        return os.path.exists(file_path)
    
    def get_file_url(self, key: str, expires_in: int = 3600) -> Optional[str]:
        """Get presigned URL for file download."""
        if not self.is_s3_available():
            return None
        
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.settings.s3_bucket, 'Key': key},
                ExpiresIn=expires_in
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            return None
    
    def cleanup_old_files(self, max_age_hours: int = 24) -> int:
        """Clean up old files from storage."""
        cleaned_count = 0
        try:
            if self.is_s3_available():
                cleaned_count = self._cleanup_s3_old_files(max_age_hours)
            else:
                cleaned_count = self._cleanup_local_old_files(max_age_hours)
            
            logger.info(f"Cleaned up {cleaned_count} old files")
            return cleaned_count
        except Exception as e:
            logger.error(f"Failed to cleanup old files: {e}")
            return 0
    
    def _cleanup_s3_old_files(self, max_age_hours: int) -> int:
        """Clean up old files from S3."""
        # Implementation for S3 cleanup
        return 0
    
    def _cleanup_local_old_files(self, max_age_hours: int) -> int:
        """Clean up old files from local storage."""
        import time
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        cleaned_count = 0
        
        for root, dirs, files in os.walk(self.settings.upload_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if current_time - os.path.getmtime(file_path) > max_age_seconds:
                    try:
                        os.remove(file_path)
                        cleaned_count += 1
                    except Exception as e:
                        logger.error(f"Failed to delete old file {file_path}: {e}")
        
        return cleaned_count

# Global storage manager instance
storage_manager = StorageManager() 