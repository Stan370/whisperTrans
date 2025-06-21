import sys
import os
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
import json
import zipfile
import tempfile
import shutil

from core.models import (
    TaskRequest, TaskResponse, TaskStatusResponse, 
    TaskStatus, TranslationTask
)
from core.task_manager import task_manager
from core.translation_service import translation_service
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
    story_name: Optional[str] = Form(None),
    source_language: str = Form(default="en"),
    target_languages: List[str] = Form(default=["zh", "ja"])
):
    """
    Create a new translation task.
    Can accept multiple .mp3 and one .json file, or a single .zip file
    containing them. If a story_name is provided, it will be used to
    identify the story. Otherwise, the zip file name is used.
    """
    try:
        audio_files = []
        text_data = {}
        processed_story_name = story_name
        
        upload_dir = storage_manager.settings.upload_dir
        os.makedirs(upload_dir, exist_ok=True)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # First, save all uploaded files and extract zips
            for file in files:
                if file.size > storage_manager.settings.max_file_size:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"File {file.filename} exceeds maximum size limit"
                    )
                
                temp_path = os.path.join(temp_dir, file.filename)
                with open(temp_path, "wb") as f:
                    f.write(await file.read())
                
                if file.filename.endswith('.zip'):
                    if not processed_story_name:
                        processed_story_name = os.path.splitext(file.filename)[0]
                    with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                        zip_ref.extractall(temp_dir)
                    os.remove(temp_path) # remove zip after extraction

            # Second, process all files in temp_dir
            for filename in os.listdir(temp_dir):
                source_path = os.path.join(temp_dir, filename)
                dest_path = os.path.join(upload_dir, filename)
                shutil.copy2(source_path, dest_path)
                
                if filename.endswith(".mp3"):
                    audio_files.append(dest_path)
                elif filename.endswith(".json"):
                    # Assuming one JSON file provides text_data for all audio
                    with open(dest_path, "r", encoding="utf-8") as f:
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
        
        # If a story name is available, associate it with the task
        if processed_story_name:
            task_manager.associate_story_with_task(
                story_name=processed_story_name,
                task_id=task_id,
                title=processed_story_name,
                languages=[source_language] + target_languages,
                segment_count=len(text_data)
            )

        logger.info(f"Created task {task_id} with {len(audio_files)} audio files for story '{processed_story_name}'")
        
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
        
        results = translation_service.get_results(task_id)
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

@router.get("/results/files")
async def list_result_files():
    """List all result files."""
    try:
        files = translation_service.list_result_files()
        return {"files": files}
        
    except Exception as e:
        logger.error(f"Failed to list result files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/results/files/{task_id}")
async def get_result_file(task_id: str):
    """Download the result file for a specific task."""
    try:
        filepath = translation_service.get_result_filepath(task_id)
        if not filepath or not os.path.exists(filepath):
            raise HTTPException(status_code=404, detail="Result file not found")
        
        filename = os.path.basename(filepath)
        return FileResponse(path=filepath, media_type='application/json', filename=filename)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get result file for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
