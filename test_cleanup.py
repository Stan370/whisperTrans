#!/usr/bin/env python3
"""
Test script to verify cleanup functionality
"""
import sys
import os
from pathlib import Path

# Add the root directory to Python path
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from core.task_manager import task_manager
from utils.logger import get_logger

logger = get_logger("test_cleanup")

def test_cleanup():
    """Test the cleanup functionality."""
    try:
        print("Testing task cleanup functionality...")
        task_manager._periodic_cleanup()
        print("Running manual cleanup...")
        cleaned = task_manager.cleanup_old_tasks(24)
        print(f"Cleaned up {cleaned} old tasks")
        print("Cleanup tests completed successfully!")
        
    except Exception as e:
        print(f"Cleanup test failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = test_cleanup()
    sys.exit(0 if success else 1) 