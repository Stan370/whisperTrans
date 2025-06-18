import json
import time
import uuid
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from config import settings, LANGUAGE_MAP
from infrastructure.redis_client import redis_client
from core.models import TranslationTask, TaskStatus, TranslationResult
from utils.logger import get_logger

logger = get_logger("task_manager")

class TaskManager:
    """Centralized task manager with Redis streams and fault tolerance."""
    
    def __init__(self):
        self.stream_key = "translation_tasks"
        self.group_name = "translation_workers"
        self.consumer_name = f"worker-{uuid.uuid4().hex[:8]}"
        self._setup_stream()
    
    def _setup_stream(self):
        """Setup Redis stream and consumer group."""
        try:
            redis_client.xgroup_create(self.stream_key, self.group_name, mkstream=True)
            logger.info(f"Redis stream setup completed: {self.stream_key}")
        except Exception as e:
            logger.error(f"Failed to setup Redis stream: {e}")
            raise
    
    def create_task(self, source_language: str, target_languages: List[str], 
                   audio_files: List[str], text_data: Dict[str, str]) -> str:
        """Create a new translation task."""
        task_id = str(uuid.uuid4())
        
        # Validate languages
        if source_language not in LANGUAGE_MAP:
            raise ValueError(f"Unsupported source language: {source_language}")
        
        for lang in target_languages:
            if lang not in LANGUAGE_MAP:
                raise ValueError(f"Unsupported target language: {lang}")
        
        task = TranslationTask(
            task_id=task_id,
            status=TaskStatus.PENDING,
            source_language=source_language,
            target_languages=target_languages,
            audio_files=audio_files,
            text_data=text_data,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        # Store task data in Redis
        task_key = f"task:{task_id}"
        redis_client.hset(task_key, mapping=task.dict())
        
        # Add task to stream
        redis_client.xadd(
            self.stream_key,
            {
                "task_id": task_id,
                "status": TaskStatus.PENDING.value,
                "timestamp": str(time.time())
            }
        )
        
        logger.info(f"Created task {task_id} with {len(audio_files)} audio files")
        return task_id
    
    def get_task(self, task_id: str) -> Optional[TranslationTask]:
        """Get task by ID."""
        task_data = redis_client.hgetall(f"task:{task_id}")
        if not task_data:
            return None
        
        # Convert string values back to proper types
        task_data['status'] = TaskStatus(task_data['status'])
        task_data['created_at'] = datetime.fromisoformat(task_data['created_at'])
        task_data['updated_at'] = datetime.fromisoformat(task_data['updated_at'])
        task_data['retry_count'] = int(task_data.get('retry_count', 0))
        task_data['progress'] = float(task_data.get('progress', 0.0))
        
        return TranslationTask(**task_data)
    
    def update_task_status(self, task_id: str, status: TaskStatus, 
                          assigned_worker: Optional[str] = None,
                          error_message: Optional[str] = None,
                          progress: Optional[float] = None) -> bool:
        """Update task status and metadata."""
        task = self.get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} not found for status update")
            return False
        
        task.status = status
        task.updated_at = datetime.utcnow()
        
        if assigned_worker:
            task.assigned_worker = assigned_worker
        if error_message:
            task.error_message = error_message
        if progress is not None:
            task.progress = progress
        
        # Store updated task
        task_key = f"task:{task_id}"
        redis_client.hset(task_key, mapping=task.dict())
        
        logger.info(f"Updated task {task_id} status to {status.value}")
        return True
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        return self.update_task_status(task_id, TaskStatus.CANCELLED)
    
    def retry_task(self, task_id: str) -> bool:
        """Retry a failed task."""
        task = self.get_task(task_id)
        if not task:
            return False
        
        if task.status != TaskStatus.FAILED:
            logger.warning(f"Cannot retry task {task_id} with status {task.status}")
            return False
        
        if task.retry_count >= settings.task_retry_limit:
            logger.warning(f"Task {task_id} has exceeded retry limit")
            return False
        
        # Increment retry count and reset status
        task.retry_count += 1
        task.status = TaskStatus.PENDING
        task.updated_at = datetime.utcnow()
        task.error_message = None
        task.progress = 0.0
        
        # Store updated task
        task_key = f"task:{task_id}"
        redis_client.hset(task_key, mapping=task.dict())
        
        # Re-add to stream for processing
        redis_client.xadd(
            self.stream_key,
            {
                "task_id": task_id,
                "status": TaskStatus.PENDING.value,
                "retry_count": str(task.retry_count),
                "timestamp": str(time.time())
            }
        )
        
        logger.info(f"Retried task {task_id} (attempt {task.retry_count})")
        return True
    
    def claim_pending_tasks(self, worker_id: str, count: int = 1) -> List[Tuple[str, TranslationTask]]:
        """Claim pending tasks for processing."""
        tasks = []
        try:
            # Read pending tasks from stream
            stream_data = redis_client.xreadgroup(
                self.group_name,
                worker_id,
                {self.stream_key: ">"},
                count=count,
                block=1000
            )
            
            for _, messages in stream_data:
                for message_id, message in messages:
                    task_id = message["task_id"]
                    task = self.get_task(task_id)
                    
                    if task and task.status == TaskStatus.PENDING:
                        # Update task status to processing
                        self.update_task_status(
                            task_id, 
                            TaskStatus.PROCESSING, 
                            assigned_worker=worker_id,
                            progress=0.1
                        )
                        tasks.append((message_id, task))
                        
        except Exception as e:
            logger.error(f"Failed to claim pending tasks: {e}")
        
        return tasks
    
    def acknowledge_task(self, message_id: str) -> bool:
        """Acknowledge task completion."""
        try:
            redis_client.xack(self.stream_key, self.group_name, message_id)
            return True
        except Exception as e:
            logger.error(f"Failed to acknowledge task {message_id}: {e}")
            return False
    
    def claim_orphaned_tasks(self, worker_id: str) -> List[Tuple[str, TranslationTask]]:
        """Claim orphaned tasks from failed workers."""
        tasks = []
        try:
            # Get pending entries list for all consumers
            pending_data = redis_client.client.xpending_range(
                self.stream_key, 
                self.group_name, 
                min="-", 
                max="+", 
                count=100
            )
            
            for entry in pending_data:
                message_id = entry['message_id']
                idle_time = entry['idle']
                
                # If task has been idle for too long, claim it
                if idle_time > settings.worker_timeout * 1000:  # Convert to milliseconds
                    claimed_messages = redis_client.xclaim(
                        self.stream_key,
                        self.group_name,
                        worker_id,
                        settings.worker_timeout * 1000,
                        message_id
                    )
                    
                    if claimed_messages:
                        task_id = claimed_messages[0][1].get("task_id")
                        if task_id:
                            task = self.get_task(task_id)
                            if task and task.status == TaskStatus.PROCESSING:
                                # Reset task to pending for retry
                                self.update_task_status(
                                    task_id,
                                    TaskStatus.PENDING,
                                    progress=0.0
                                )
                                tasks.append((message_id, task))
                                logger.info(f"Claimed orphaned task {task_id}")
        
        except Exception as e:
            logger.error(f"Failed to claim orphaned tasks: {e}")
        
        return tasks
    
    def get_all_tasks(self, status: Optional[TaskStatus] = None, 
                     limit: int = 100) -> List[TranslationTask]:
        """Get all tasks, optionally filtered by status."""
        tasks = []
        try:
            for key in redis_client.scan_iter("task:*", count=limit):
                task_data = redis_client.hgetall(key)
                if task_data:
                    # Convert string values back to proper types
                    task_data['status'] = TaskStatus(task_data['status'])
                    task_data['created_at'] = datetime.fromisoformat(task_data['created_at'])
                    task_data['updated_at'] = datetime.fromisoformat(task_data['updated_at'])
                    task_data['retry_count'] = int(task_data.get('retry_count', 0))
                    task_data['progress'] = float(task_data.get('progress', 0.0))
                    
                    task = TranslationTask(**task_data)
                    if status is None or task.status == status:
                        tasks.append(task)
        except Exception as e:
            logger.error(f"Failed to get all tasks: {e}")
        
        return tasks
    
    def store_results(self, task_id: str, results: Dict[str, TranslationResult]) -> bool:
        """Store translation results."""
        try:
            results_key = f"results:{task_id}"
            results_data = {
                task_id: json.dumps([result.dict() for result in results.values()])
            }
            redis_client.hset(results_key, mapping=results_data)
            logger.info(f"Stored results for task {task_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to store results for task {task_id}: {e}")
            return False
    
    def get_results(self, task_id: str) -> Optional[Dict[str, TranslationResult]]:
        """Get translation results."""
        try:
            results_key = f"results:{task_id}"
            results_data = redis_client.hget(results_key, task_id)
            if not results_data:
                return None
            
            results_list = json.loads(results_data)
            results = {}
            for result_data in results_list:
                result = TranslationResult(**result_data)
                results[result.file_id] = result
            
            return results
        except Exception as e:
            logger.error(f"Failed to get results for task {task_id}: {e}")
            return None
    
    def cleanup_old_tasks(self, max_age_hours: int = 24) -> int:
        """Clean up old completed/failed tasks."""
        cleaned_count = 0
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        try:
            for key in redis_client.scan_iter("task:*"):
                task_data = redis_client.hgetall(key)
                if task_data:
                    updated_at = datetime.fromisoformat(task_data['updated_at'])
                    status = TaskStatus(task_data['status'])
                    
                    # Clean up old completed/failed/cancelled tasks
                    if (status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED] 
                        and updated_at < cutoff_time):
                        task_id = key.split(":")[1]
                        
                        # Delete task and results
                        redis_client.delete(key)
                        redis_client.delete(f"results:{task_id}")
                        cleaned_count += 1
            
            logger.info(f"Cleaned up {cleaned_count} old tasks")
            return cleaned_count
        except Exception as e:
            logger.error(f"Failed to cleanup old tasks: {e}")
            return 0
    
    def get_task_statistics(self) -> Dict[str, int]:
        """Get task statistics."""
        stats = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "total": 0
        }
        
        try:
            for key in redis_client.scan_iter("task:*"):
                task_data = redis_client.hgetall(key)
                if task_data:
                    status = TaskStatus(task_data['status'])
                    stats[status.value] += 1
                    stats["total"] += 1
        except Exception as e:
            logger.error(f"Failed to get task statistics: {e}")
        
        return stats

# Global task manager instance
task_manager = TaskManager() 