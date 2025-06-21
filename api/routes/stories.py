import sys
import os
from pathlib import Path
from typing import Optional
from enum import Enum
from fastapi import APIRouter, HTTPException, Query
from core.task_manager import task_manager
from core.translation_service import translation_service
from utils.logger import get_logger

# Add the root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))
logger = get_logger("api_stories")

router = APIRouter(prefix="/api/v1/story", tags=["stories"])

class TextSource(str, Enum):
    TEXT = "TEXT"
    AUDIO = "AUDIO"
    TRANSLATION = "TRANSLATION"

@router.get("/{story_name}/text")
async def get_story_text(
    story_name: str,
    lang: str = Query(..., description="Language code (e.g., 'en', 'zh')"),
    text_id: str = Query(..., description="Text segment ID"),
    source: TextSource = Query(..., description="Source of the text")
):
    """
    Get a specific text segment from a story.
    This provides a user-friendly way to query content without needing the task_id.
    """
    try:
        # 1. Get story info to find the task_id
        story_info = task_manager.get_story_info(story_name)
        if not story_info:
            raise HTTPException(status_code=404, detail=f"Story '{story_name}' not found.")
        
        task_id = story_info.get("task_id")
        if not task_id:
            raise HTTPException(status_code=404, detail=f"Task ID not found for story '{story_name}'.")

        # 2. Get the results for the task
        packed_data = translation_service.get_results(task_id)
        if not packed_data:
            raise HTTPException(status_code=404, detail=f"Results not found for task {task_id}.")

        # 3. Get the specific text using the provided service function
        content = translation_service.get_translated_text(
            packed_data=packed_data,
            language=lang,
            text_id=text_id,
            source=source.value
        )

        if content is None:
            raise HTTPException(status_code=404, detail=f"Content not found for lang='{lang}', text_id='{text_id}', source='{source}'.")
        
        return {"content": content}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get story text for '{story_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e)) 