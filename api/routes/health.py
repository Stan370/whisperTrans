import sys
import os
from pathlib import Path

# Add the root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from fastapi import APIRouter, HTTPException
import psutil
from datetime import datetime, UTC
from typing import Dict, List

from core.models import HealthCheckResponse, WorkerStatus
from infrastructure.redis_client import redis_client
from infrastructure.storage import storage_manager
from utils.logger import get_logger

logger = get_logger("api_health")

router = APIRouter(prefix="/api/v1/health", tags=["health"])

@router.get("/", response_model=HealthCheckResponse)
async def health_check():
    """Comprehensive health check endpoint."""
    try:
        # Check system resources
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
        
        # Check Redis connection
        redis_connected = redis_client.health_check()
        
        # Check storage availability
        storage_available = storage_manager.is_s3_available() or True  # Local storage always available
        
        # Determine overall status
        if redis_connected and storage_available and memory_usage < 90:
            status = "healthy"
        else:
            status = "degraded"
        
        return HealthCheckResponse(
            status=status,
            timestamp=datetime.now(UTC),
            version="1.0.0",
            memory_usage=memory_usage,
            redis_connected=redis_connected,
            storage_available=storage_available
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Health check failed")

@router.get("/redis")
async def redis_health_check():
    """Redis-specific health check."""
    try:
        is_healthy = redis_client.health_check()
        if not is_healthy:
            raise HTTPException(status_code=503, detail="Redis connection failed")
        
        return {"status": "healthy", "service": "redis"}
        
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        raise HTTPException(status_code=503, detail="Redis health check failed")

@router.get("/storage")
async def storage_health_check():
    """Storage-specific health check."""
    try:
        # Test storage availability
        if storage_manager.is_s3_available():
            # Try a simple S3 operation
            try:
                # This would test S3 connectivity
                pass
            except Exception:
                raise HTTPException(status_code=503, detail="S3 storage unavailable")
        else:
            # Test local storage
            test_file = "temp/health_test.tmp"
            try:
                with open(test_file, "w") as f:
                    f.write("health test")
                os.remove(test_file)
            except Exception:
                raise HTTPException(status_code=503, detail="Local storage unavailable")
        
        return {"status": "healthy", "service": "storage"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Storage health check failed: {e}")
        raise HTTPException(status_code=503, detail="Storage health check failed")

@router.get("/workers", response_model=List[WorkerStatus])
async def get_worker_status():
    """Get status of all active workers."""
    try:
        workers = []
        
        # Scan for worker keys in Redis
        for key in redis_client.scan_iter("worker:*:heartbeat"):
            worker_id = key.split(":")[1]
            
            # Get worker data
            worker_data = redis_client.hgetall(f"worker:{worker_id}")
            if worker_data:
                try:
                    workers.append(WorkerStatus(
                        worker_id=worker_id,
                        status=worker_data.get("status", "unknown"),
                        last_heartbeat=datetime.fromisoformat(worker_data.get("last_heartbeat", datetime.now(UTC).isoformat())),
                        memory_usage=0.0,  # Would need to be reported by worker
                        cpu_usage=0.0,     # Would need to be reported by worker
                        active_tasks=int(worker_data.get("active_tasks", 0)),
                        completed_tasks=int(worker_data.get("completed_tasks", 0)),
                        failed_tasks=int(worker_data.get("failed_tasks", 0))
                    ))
                except Exception as e:
                    logger.warning(f"Failed to parse worker data for {worker_id}: {e}")
        
        return workers
        
    except Exception as e:
        logger.error(f"Failed to get worker status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get worker status")

@router.get("/system")
async def get_system_info():
    """Get system resource information."""
    try:
        # CPU information
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        
        # Memory information
        memory = psutil.virtual_memory()
        memory_info = {
            "total_gb": round(memory.total / (1024**3), 2),
            "available_gb": round(memory.available / (1024**3), 2),
            "used_gb": round(memory.used / (1024**3), 2),
            "percent": memory.percent
        }
        
        # Disk information
        disk = psutil.disk_usage('/')
        disk_info = {
            "total_gb": round(disk.total / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "percent": round((disk.used / disk.total) * 100, 2)
        }
        
        return {
            "cpu": {
                "percent": cpu_percent,
                "count": cpu_count
            },
            "memory": memory_info,
            "disk": disk_info,
            "timestamp": datetime.now(UTC).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get system info: {e}")
        raise HTTPException(status_code=500, detail="Failed to get system information")

@router.get("/metrics")
async def get_metrics():
    """Get system metrics for monitoring."""
    try:
        # Get task statistics
        from core.task_manager import task_manager
        task_stats = task_manager.get_task_statistics()
        
        # Get system metrics
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=1)
        
        # Get worker count
        worker_count = len(list(redis_client.scan_iter("worker:*:heartbeat")))
        
        metrics = {
            "tasks": task_stats,
            "system": {
                "cpu_percent": cpu,
                "memory_percent": memory.percent,
                "memory_available_gb": round(memory.available / (1024**3), 2)
            },
            "workers": {
                "active_count": worker_count
            },
            "timestamp": datetime.now(UTC).isoformat()
        }
        
        return metrics
        
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get metrics") 