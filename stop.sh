#!/bin/bash

echo "Stopping all translation system services..."

# Stop Python processes
    echo "Shutting down services..."
    pkill -f "python api/main.py" 2>/dev/null
    pkill -f "python ui/gradio_interface.py" 2>/dev/null
    pkill -f "python workers/worker.py" 2>/dev/null

# Stop Redis server (only if we started it)
pkill -f "redis-server" 2>/dev/null

echo "All services stopped" 