from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, UTC
from enum import Enum

class TaskStatus(str, Enum):
    """Task status enumeration."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY = "retry"

class TranslationTask(BaseModel):
    """Translation task model."""
    task_id: str = Field(..., description="Unique task identifier")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current task status")
    source_language: str = Field(..., description="Source language code")
    target_languages: List[str] = Field(..., description="Target language codes")
    audio_files: List[str] = Field(..., description="List of audio file paths")
    text_data: Dict[str, str] = Field(default_factory=dict, description="Reference text data")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Task creation timestamp")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Last update timestamp")
    assigned_worker: Optional[str] = Field(default=None, description="Worker assigned to task")
    error_message: Optional[str] = Field(default=None, description="Error message if task failed")
    retry_count: int = Field(default=0, description="Number of retry attempts")
    progress: float = Field(default=0.0, description="Task progress (0.0 to 1.0)")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class TaskRequest(BaseModel):
    """Task creation request model."""
    source_language: str = Field(default="en", description="Source language code")
    target_languages: List[str] = Field(default=["zh", "ja"], description="Target language codes")
    original_text: Optional[str] = Field(default=None, description="Optional reference text")

class TaskResponse(BaseModel):
    """Task response model."""
    task_id: str = Field(..., description="Task identifier")
    status: TaskStatus = Field(..., description="Task status")
    message: str = Field(..., description="Response message")

class TaskStatusResponse(BaseModel):
    """Task status response model."""
    task_id: str = Field(..., description="Task identifier")
    status: TaskStatus = Field(..., description="Task status")
    progress: float = Field(..., description="Task progress")
    message: Optional[str] = Field(default=None, description="Status message")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    assigned_worker: Optional[str] = Field(default=None, description="Assigned worker")
    error_message: Optional[str] = Field(default=None, description="Error message")

class HealthCheckResponse(BaseModel):
    """Health check response model."""
    status: str = Field(..., description="Service status")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Check timestamp")
    version: str = Field(default="1.0.0", description="Service version")
    memory_usage: float = Field(..., description="Memory usage percentage")
    redis_connected: bool = Field(..., description="Redis connection status")
    storage_available: bool = Field(..., description="Storage availability")

class WorkerStatus(BaseModel):
    """Worker status model."""
    worker_id: str = Field(..., description="Worker identifier")
    status: str = Field(..., description="Worker status")
    last_heartbeat: datetime = Field(..., description="Last heartbeat timestamp")
    memory_usage: float = Field(..., description="Memory usage percentage")
    cpu_usage: float = Field(..., description="CPU usage percentage")
    active_tasks: int = Field(..., description="Number of active tasks")
    completed_tasks: int = Field(..., description="Number of completed tasks")
    failed_tasks: int = Field(..., description="Number of failed tasks")

class FileUploadResponse(BaseModel):
    """File upload response model."""
    file_id: str = Field(..., description="File identifier")
    filename: str = Field(..., description="Original filename")
    size: int = Field(..., description="File size in bytes")
    storage_path: str = Field(..., description="Storage path")
    upload_time: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Upload timestamp") 