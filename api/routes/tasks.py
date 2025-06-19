import sys
import os
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse
import json
import zipfile
import tempfile

from core.models import (
    TaskRequest, TaskResponse, TaskStatusResponse, 
    TaskStatus, TranslationTask
)
from core.task_manager import task_manager
from infrastructure.storage import storage_manager
from utils.logger import get_logger

# Add the root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))
logger = get_logger("api_tasks")

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

@router.post("/", response_model=TaskResponse)
async def create_task(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    source_language: str = Form(default="en"),
    target_languages: List[str] = Form(default=["zh", "ja"])
):
    """Create a new translation task."""
    try:
        audio_files = []
        text_data = {}
        
        # Process uploaded files
        for file in files:
            # Validate file size
            if file.size > storage_manager.settings.max_file_size:
                raise HTTPException(
                    status_code=400, 
                    detail=f"File {file.filename} exceeds maximum size limit"
                )
            
            # Save file to storage
            file_path = os.path.join(storage_manager.settings.upload_dir, file.filename)
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
            
            # Handle different file types - only MP3 allowed
            if file.filename.endswith(".mp3"):
                audio_files.append(file_path)
            elif file.filename.endswith(".json"):
                with open(file_path, "r", encoding="utf-8") as f:
                    text_data = json.load(f)
        
        if not audio_files:
            raise HTTPException(
                status_code=400, 
                detail="No MP3 audio files found in upload"
            )
        
        # Create translation task
        task_id = task_manager.create_task(
            source_language=source_language,
            target_languages=target_languages,
            audio_files=audio_files,
            text_data=text_data
        )
        
        logger.info(f"Created task {task_id} with {len(audio_files)} audio files")
        
        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message="Task created successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """Get status of a translation task."""
    try:
        task = task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return TaskStatusResponse(
            task_id=task.task_id,
            status=task.status,
            progress=task.progress,
            message=None,
            created_at=task.created_at,
            updated_at=task.updated_at,
            assigned_worker=task.assigned_worker,
            error_message=task.error_message
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task status {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{task_id}/results")
async def get_task_results(task_id: str):
    """Get results of a completed translation task."""
    try:
        task = task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        if task.status != TaskStatus.COMPLETED:
            raise HTTPException(
                status_code=400, 
                detail=f"Task not completed. Current status: {task.status}"
            )
        
        results = task_manager.get_results(task_id)
        if not results:
            raise HTTPException(status_code=404, detail="Results not found")
        
        return results
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task results {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: str):
    """Cancel a translation task."""
    try:
        success = task_manager.cancel_task(task_id)
        if not success:
            raise HTTPException(status_code=404, detail="Task not found")
        
        logger.info(f"Cancelled task {task_id}")
        
        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.CANCELLED,
            message="Task cancelled successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(task_id: str):
    """Retry a failed translation task."""
    try:
        success = task_manager.retry_task(task_id)
        if not success:
            raise HTTPException(
                status_code=400, 
                detail="Task cannot be retried or not found"
            )
        
        logger.info(f"Retried task {task_id}")
        
        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message="Task retried successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retry task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=List[TaskStatusResponse])
async def list_tasks(
    status: Optional[TaskStatus] = None,
    limit: int = 100
):
    """List all translation tasks, optionally filtered by status."""
    try:
        tasks = task_manager.get_all_tasks(status=status, limit=limit)
        
        return [
            TaskStatusResponse(
                task_id=task.task_id,
                status=task.status,
                progress=task.progress,
                message=None,
                created_at=task.created_at,
                updated_at=task.updated_at,
                assigned_worker=task.assigned_worker,
                error_message=task.error_message
            )
            for task in tasks
        ]
        
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/statistics/summary")
async def get_task_statistics():
    """Get task statistics."""
    try:
        stats = task_manager.get_task_statistics()
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get task statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
