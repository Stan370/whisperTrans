import sys
import os
from pathlib import Path
import redis
import time
from typing import Optional, Dict, Any, List
from utils.config import settings
from utils.logger import get_logger

# Add the root directory to Python path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
logger = get_logger("redis_client")

class RedisClient:
    """Centralized Redis client with connection pooling and error handling."""
    
    def __init__(self):
        self._client: Optional[redis.Redis] = None
        self._connection_pool: Optional[redis.ConnectionPool] = None
        self._connect()
    
    def _connect(self):
        """Establish Redis connection with retry logic."""
        try:
            self._connection_pool = redis.ConnectionPool(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password,
                decode_responses=True,
                max_connections=20,
                retry_on_timeout=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            
            self._client = redis.Redis(connection_pool=self._connection_pool)
            
            # Test connection
            self._client.ping()
            logger.info("Redis connection established successfully")
            
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error connecting to Redis: {e}")
            raise
    
    @property
    def client(self) -> redis.Redis:
        """Get Redis client instance."""
        if not self._client:
            self._connect()
        return self._client
    
    def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            self.client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
    
    def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """Set key-value pair with optional expiration."""
        try:
            return self.client.set(key, value, ex=ex)
        except Exception as e:
            logger.error(f"Failed to set key {key}: {e}")
            return False
    
    def get(self, key: str) -> Optional[str]:
        """Get value by key."""
        try:
            return self.client.get(key)
        except Exception as e:
            logger.error(f"Failed to get key {key}: {e}")
            return None
    
    def hset(self, key: str, mapping: Dict[str, Any]) -> int:
        """Set hash fields."""
        try:
            return self.client.hset(key, mapping=mapping)
        except Exception as e:
            logger.error(f"Failed to hset key {key}: {e}")
            return 0
    
    def hget(self, key: str, field: str) -> Optional[str]:
        """Get hash field value."""
        try:
            return self.client.hget(key, field)
        except Exception as e:
            logger.error(f"Failed to hget key {key}, field {field}: {e}")
            return None
    
    def hgetall(self, key: str) -> Dict[str, str]:
        """Get all hash fields."""
        try:
            return self.client.hgetall(key)
        except Exception as e:
            logger.error(f"Failed to hgetall key {key}: {e}")
            return {}
    
    def delete(self, key: str) -> int:
        """Delete key."""
        try:
            return self.client.delete(key)
        except Exception as e:
            logger.error(f"Failed to delete key {key}: {e}")
            return 0
    
    def exists(self, key: str) -> bool:
        """Check if key exists."""
        try:
            return bool(self.client.exists(key))
        except Exception as e:
            logger.error(f"Failed to check existence of key {key}: {e}")
            return False
    
    def scan_iter(self, pattern: str = "*", count: int = 100) -> List[str]:
        """Scan keys matching pattern."""
        try:
            return list(self.client.scan_iter(pattern, count=count))
        except Exception as e:
            logger.error(f"Failed to scan keys with pattern {pattern}: {e}")
            return []
    
    def xadd(self, stream: str, fields: Dict[str, str], maxlen: Optional[int] = None) -> str:
        """Add entry to stream."""
        try:
            return self.client.xadd(stream, fields, maxlen=maxlen)
        except Exception as e:
            logger.error(f"Failed to xadd to stream {stream}: {e}")
            raise
    
    def xreadgroup(self, group: str, consumer: str, streams: Dict[str, str], 
                   count: int = 1, block: int = 1000) -> List:
        """Read from stream with consumer group."""
        try:
            return self.client.xreadgroup(group, consumer, streams, count=count, block=block)
        except Exception as e:
            logger.error(f"Failed to xreadgroup: {e}")
            return []
    
    def xack(self, stream: str, group: str, *message_ids: str) -> int:
        """Acknowledge messages in stream."""
        try:
            return self.client.xack(stream, group, *message_ids)
        except Exception as e:
            logger.error(f"Failed to xack messages: {e}")
            return 0
    
    def xclaim(self, stream: str, group: str, consumer: str, 
               min_idle_time: int, *message_ids: str) -> List:
        """Claim pending messages."""
        try:
            return self.client.xclaim(stream, group, consumer, min_idle_time, *message_ids)
        except Exception as e:
            logger.error(f"Failed to xclaim messages: {e}")
            return []
    
    def xgroup_create(self, stream: str, group: str, mkstream: bool = True) -> bool:
        """Create consumer group."""
        try:
            self.client.xgroup_create(stream, group, mkstream=mkstream)
            return True
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" in str(e):
                return True  # Group already exists
            logger.error(f"Failed to create consumer group: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to create consumer group: {e}")
            return False
    
    def xinfo_consumers(self, stream: str, group: str) -> list:
        """Get info about consumers in a group."""
        try:
            return self.client.xinfo_consumers(stream, group)
        except Exception as e:
            logger.error(f"Failed to get consumers info for {stream}/{group}: {e}")
            return []

    def xgroup_delconsumer(self, stream: str, group: str, consumer: str) -> int:
        """Delete a consumer from a group."""
        try:
            return self.client.xgroup_delconsumer(stream, group, consumer)
        except Exception as e:
            logger.error(f"Failed to delete consumer {consumer} from {stream}/{group}: {e}")
            return 0

    def clean_dead_consumers(self, stream: str, group: str, idle_ms: int = 3600000):
        """Remove consumers idle for more than idle_ms milliseconds."""
        consumers = self.xinfo_consumers(stream, group)
        removed = 0
        for c in consumers:
            if c.get("idle", 0) > idle_ms:
                name = c.get("name")
                if name:
                    self.xgroup_delconsumer(stream, group, name)
                    logger.info(f"Removed dead consumer {name} from {stream}/{group} (idle {c['idle']} ms)")
                    removed += 1
        return removed
    
    def close(self):
        """Close Redis connection."""
        if self._client:
            self._client.close()
        if self._connection_pool:
            self._connection_pool.disconnect()
        logger.info("Redis connection closed")

# Global Redis client instance
redis_client = RedisClient() 