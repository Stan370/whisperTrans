import os
from typing import List, Dict, Optional
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

class Settings(BaseSettings):
    # Environment
    environment: str = Field(default="development", env="ENVIRONMENT")
    debug: bool = Field(default=True, env="DEBUG")
    
    # API Configuration
    api_host: str = Field(default="0.0.0.0", env="API_HOST")
    api_port: int = Field(default=8000, env="API_PORT")
    api_workers: int = Field(default=5, env="API_WORKERS")
    
    # Redis Configuration
    redis_host: str = Field(default="localhost", env="REDIS_HOST")
    redis_port: int = Field(default=6379, env="REDIS_PORT")
    redis_db: int = Field(default=0, env="REDIS_DB")
    redis_password: Optional[str] = Field(default=None, env="REDIS_PASSWORD")
    
    # S3 Configuration
    s3_bucket: str = Field(default="whisper-trans", env="S3_BUCKET")
    s3_region: str = Field(default="us-east-1", env="S3_REGION")
    s3_access_key: Optional[str] = Field(default=None, env="S3_ACCESS_KEY")
    s3_secret_key: Optional[str] = Field(default=None, env="S3_SECRET_KEY")
    
    # Translation Configuration
    google_api_key: str = Field(default="dummy_key_for_testing", env="GOOGLE_API_KEY")
    supported_languages: List[str] = Field(default=["en", "zh-CN", "zh-TW", "ja"], env="SUPPORTED_LANGUAGES")
    
    # Worker Configuration
    worker_memory_limit: int = Field(default=90, env="WORKER_MEMORY_LIMIT")
    worker_batch_size: int = Field(default=1, env="WORKER_BATCH_SIZE")
    worker_heartbeat_interval: int = Field(default=30, env="WORKER_HEARTBEAT_INTERVAL")
    worker_timeout: int = Field(default=300, env="WORKER_TIMEOUT")
    worker_max_threads: int = Field(default=10, env="WORKER_MAX_THREADS")
    
    # File Configuration
    upload_dir: str = Field(default="temp/uploads", env="UPLOAD_DIR")
    result_dir: str = Field(default="temp/results", env="RESULT_DIR")
    max_file_size: int = Field(default=100 * 1024 * 1024, env="MAX_FILE_SIZE")  # 100MB
    allowed_audio_formats: List[str] = Field(default=[".mp3"], env="ALLOWED_AUDIO_FORMATS")  # Only MP3
    
    # Logging Configuration
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_format: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s", env="LOG_FORMAT")
    
    # Task Configuration
    task_retry_limit: int = Field(default=3, env="TASK_RETRY_LIMIT")
    task_timeout: int = Field(default=1800, env="TASK_TIMEOUT")  # 30 minutes
    
    # STT Configuration
    whisper_model: str = Field(default="base", env="WHISPER_MODEL")
    wer_threshold: float = Field(default=0.3, env="WER_THRESHOLD")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

# Language mapping
LANGUAGE_MAP = {
    "en": "English",
    "zh": "Chinese (Simplified)",
    "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish"
}

# Create settings instance
try:
    settings = Settings()
    print(f"Configuration loaded successfully. Environment: {settings.environment}")
except Exception as e:
    print(f"Warning: Configuration loading failed: {e}")
    print("Using default configuration values.")
    # Create a minimal settings object with defaults
    settings = Settings()

# Environment-specific overrides
if settings.environment == "production":
    settings.debug = False
    settings.log_level = "WARNING"
elif settings.environment == "staging":
    settings.debug = False
    settings.log_level = "INFO" 