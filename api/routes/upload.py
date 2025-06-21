import sys
import os
from pathlib import Path
from typing import List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
import json
import zipfile
import tempfile
import shutil

# Add the root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from core.models import TaskResponse, TaskStatus
from core.task_manager import task_manager
from utils.logger import get_logger
from infrastructure.storage import storage_manager

logger = get_logger("api_upload")

upload_router = APIRouter(prefix="/api/v1", tags=["upload"])

@upload_router.post("/upload")
async def upload_files(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    source_language: str = Form(default="en"),
    target_languages: List[str] = Form(default=["zh", "ja"])
):
    """Unified upload endpoint: Accepts either a ZIP file or a set of MP3/JSON files."""
    try:
        # If a single file and it's a ZIP, process as ZIP
        if len(files) == 1 and files[0].filename.endswith('.zip'):
            zip_file = files[0]
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = os.path.join(temp_dir, zip_file.filename)
                logger.info(f"os.path.join(temp_dir, zip_file.filename): {zip_path}")
                with open(zip_path, "wb") as f:
                    content = await zip_file.read()
                    f.write(content)
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                audio_files = []
                text_data = {}
                for filename in os.listdir(temp_dir):
                    file_path = os.path.join(temp_dir, filename)
                    logger.info(f"os.path.join(temp_dir, filename): {file_path}")
                    if filename.endswith('.mp3'):
                        # Copy to persistent upload directory
                        dest_path = os.path.join(storage_manager.settings.upload_dir, filename)
                        logger.info(f"os.path.join(storage_manager.settings.upload_dir, filename): {dest_path}")
                        shutil.copy(file_path, dest_path)
                        audio_files.append(dest_path)
                    elif filename.endswith('.json'):
                        with open(file_path, 'r', encoding='utf-8') as f:
                            text_data = json.load(f)
                if not audio_files:
                    raise HTTPException(
                        status_code=400,
                        detail="No MP3 audio files found in ZIP archive"
                    )
                task_id = task_manager.create_task(
                    source_language=source_language,
                    target_languages=target_languages,
                    audio_files=audio_files,
                    text_data=text_data
                )
                logger.info(f"Created task {task_id} from ZIP upload with {len(audio_files)} audio files")
                return TaskResponse(
                    task_id=task_id,
                    status=TaskStatus.PENDING,
                    message="ZIP file uploaded and task created successfully"
                )
        else:
            # Otherwise, process as direct MP3/JSON upload
            with tempfile.TemporaryDirectory() as temp_dir:
                audio_files = []
                text_data = {}
                for file in files:
                    filename = file.filename
                    if not filename.endswith(('.mp3', '.json')):
                        continue  # Skip unsupported files
                    file_path = os.path.join(temp_dir, filename)
                    logger.info(f"os.path.join(temp_dir, filename): {file_path}")
                    with open(file_path, "wb") as buffer:
                        shutil.copyfileobj(file.file, buffer)
                    if filename.endswith('.mp3'):
                        # Copy to persistent upload directory
                        dest_path = os.path.join(storage_manager.settings.upload_dir, filename)
                        logger.info(f"os.path.join(storage_manager.settings.upload_dir, filename): {dest_path}")
                        shutil.copy(file_path, dest_path)
                        audio_files.append(dest_path)
                    elif filename.endswith('.json'):
                        with open(file_path, 'r', encoding='utf-8') as f:
                            text_data = json.load(f)
                if not audio_files:
                    raise HTTPException(
                        status_code=400,
                        detail="At least one MP3 audio file is required"
                    )
                task_id = task_manager.create_task(
                    source_language=source_language,
                    target_languages=target_languages,
                    audio_files=audio_files,
                    text_data=text_data
                )
                logger.info(f"Created task {task_id} from direct audio upload with {len(audio_files)} MP3s")
                return TaskResponse(
                    task_id=task_id,
                    status=TaskStatus.PENDING,
                    message="Audio files uploaded and task created successfully"
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process unified upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# The following endpoints are now deprecated in favor of /upload/files
# @upload_router.post("/upload/zip")
# async def upload_zip_file(...):
#     ...
# @upload_router.post("/upload/audio")
# async def upload_audio_files(...):
#     ...
