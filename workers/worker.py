import os
import time
import uuid
import signal
import sys
from typing import Optional
from datetime import datetime
from config import settings
from core.task_manager import task_manager
from core.translation_service import translation_service
from core.models import TaskStatus
from infrastructure.redis_client import redis_client
from utils.logger import get_logger

logger = get_logger("worker")

class TranslationWorker:
    """Standalone translation worker process."""
    
    def __init__(self):
        self.worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        self.running = False
        self.last_heartbeat = datetime.utcnow()
        self.active_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info(f"Translation worker {self.worker_id} initialized")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    def _send_heartbeat(self):
        """Send heartbeat to Redis."""
        try:
            heartbeat_data = {
                "worker_id": self.worker_id,
                "status": "active" if self.running else "stopping",
                "last_heartbeat": datetime.utcnow().isoformat(),
                "active_tasks": self.active_tasks,
                "completed_tasks": self.completed_tasks,
                "failed_tasks": self.failed_tasks
            }
            
            redis_client.hset(f"worker:{self.worker_id}", mapping=heartbeat_data)
            redis_client.set(f"worker:{self.worker_id}:heartbeat", time.time(), ex=60)
            
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")
    
    def _check_health(self) -> bool:
        """Check if worker is healthy."""
        try:
            # Check system resources
            if not translation_service.is_system_healthy():
                logger.warning("System resources insufficient, skipping task processing")
                return False
            
            # Check Redis connection
            if not redis_client.health_check():
                logger.error("Redis connection lost")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    def _process_task(self, task_id: str, message_id: str) -> bool:
        """Process a single translation task."""
        try:
            self.active_tasks += 1
            logger.info(f"Starting to process task {task_id}")
            
            # Get task details
            task = task_manager.get_task(task_id)
            if not task:
                logger.error(f"Task {task_id} not found")
                return False
            
            # Update progress
            task_manager.update_task_status(task_id, TaskStatus.PROCESSING, progress=0.2)
            
            # Process the task
            results = translation_service.process_task(task)
            
            # Update progress
            task_manager.update_task_status(task_id, TaskStatus.PROCESSING, progress=0.8)
            
            # Store results
            if not task_manager.store_results(task_id, results):
                raise Exception("Failed to store results")
            
            # Mark task as completed
            task_manager.update_task_status(task_id, TaskStatus.COMPLETED, progress=1.0)
            
            # Acknowledge task completion
            task_manager.acknowledge_task(message_id)
            
            self.completed_tasks += 1
            logger.info(f"Successfully completed task {task_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to process task {task_id}: {e}")
            
            # Mark task as failed
            task_manager.update_task_status(
                task_id, 
                TaskStatus.FAILED, 
                error_message=str(e)
            )
            
            # Acknowledge task to remove from pending list
            task_manager.acknowledge_task(message_id)
            
            self.failed_tasks += 1
            return False
            
        finally:
            self.active_tasks -= 1
    
    def _claim_orphaned_tasks(self):
        """Claim orphaned tasks from failed workers."""
        try:
            orphaned_tasks = task_manager.claim_orphaned_tasks(self.worker_id)
            if orphaned_tasks:
                logger.info(f"Claimed {len(orphaned_tasks)} orphaned tasks")
                return orphaned_tasks
        except Exception as e:
            logger.error(f"Failed to claim orphaned tasks: {e}")
        
        return []
    
    def run(self):
        """Main worker loop."""
        self.running = True
        logger.info(f"Translation worker {self.worker_id} started")
        
        try:
            while self.running:
                # Send heartbeat
                self._send_heartbeat()
                
                # Check health
                if not self._check_health():
                    time.sleep(10)
                    continue
                
                # Claim orphaned tasks first
                orphaned_tasks = self._claim_orphaned_tasks()
                for message_id, task in orphaned_tasks:
                    if not self.running:
                        break
                    self._process_task(task.task_id, message_id)
                
                # Claim new pending tasks
                if self.running:
                    pending_tasks = task_manager.claim_pending_tasks(
                        self.worker_id, 
                        count=settings.worker_batch_size
                    )
                    
                    for message_id, task in pending_tasks:
                        if not self.running:
                            break
                        self._process_task(task.task_id, message_id)
                
                # Sleep between iterations
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
        finally:
            self._cleanup()
    
    def _cleanup(self):
        """Cleanup resources before shutdown."""
        try:
            logger.info("Cleaning up worker resources...")
            
            # Mark worker as stopped
            self.running = False
            self._send_heartbeat()
            
            # Remove worker from Redis
            redis_client.delete(f"worker:{self.worker_id}")
            redis_client.delete(f"worker:{self.worker_id}:heartbeat")
            
            logger.info(f"Worker {self.worker_id} shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

def main():
    """Main entry point for worker process."""
    try:
        # Create and run worker
        worker = TranslationWorker()
        worker.run()
        
    except Exception as e:
        logger.error(f"Worker startup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 