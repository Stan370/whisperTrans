#!/bin/bash

# Startup script for local development only.
# Use `docker-compose` for deployment or containerized environments.
# Function to check if a command exists
check_command() {
    if ! command -v $1 &> /dev/null; then
        echo "Error: $1 is not installed"
        exit 1
    fi
    if [ "$1" == "docker" ]; then
        echo "Use docker-compose instead:"
        echo "  make build && make up"
        exit 0
    fi
}
export PYTHONPATH=$(pwd)

# Store PIDs for cleanup
API_PID=""
GRADIO_PID=""
WORKER_PIDS=()

# Function to cleanup background processes
cleanup() {
    echo "Shutting down services..."
    
    # Stop workers gracefully
    echo "Stopping workers..."
    for pid in "${WORKER_PIDS[@]}"; do
        if kill -0 $pid 2>/dev/null; then
            kill $pid
        fi
    done
    
    # Wait for workers to finish
    for pid in "${WORKER_PIDS[@]}"; do
        if kill -0 $pid 2>/dev/null; then
            wait $pid 2>/dev/null
        fi
    done
    
    # Stop API and Gradio
    if [ ! -z "$API_PID" ] && kill -0 $API_PID 2>/dev/null; then
        echo "Stopping FastAPI backend..."
        kill $API_PID
        wait $API_PID 2>/dev/null
    fi
    
    if [ ! -z "$GRADIO_PID" ] && kill -0 $GRADIO_PID 2>/dev/null; then
        echo "Stopping Gradio UI..."
        kill $GRADIO_PID
        wait $GRADIO_PID 2>/dev/null
    fi
    
    # Clean up old tasks before shutting down Redis
    echo "Cleaning up old tasks..."
    python -c "
import sys
sys.path.insert(0, '.')
from core.task_manager import task_manager
try:
    cleaned = task_manager.cleanup_old_tasks(24)
    print(f'Cleaned up {cleaned} old tasks')
except Exception as e:
    print(f'Failed to cleanup tasks: {e}')
"
    
    # Stop Redis
    echo "Stopping Redis server..."
    redis-cli shutdown 2>/dev/null || echo "Redis already stopped"
    
    echo "All services stopped"
    exit 0
}

# Set up signal handlers for graceful shutdown
trap cleanup SIGINT SIGTERM

# Check for required commands
echo "Checking dependencies..."
check_command pip
check_command python
check_command redis-server

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo "Creating directories..."
mkdir -p temp/uploads
mkdir -p temp/results
mkdir -p logs

# Start Redis server if not running
echo "Starting Redis server..."
redis-server --daemonize yes 2>/dev/null || echo "Redis already running"

# Wait for Redis to start
sleep 2

# Check Redis connection
if ! redis-cli ping > /dev/null 2>&1; then
    echo "Error: Redis server failed to start"
    exit 1
fi

echo "Redis server is running"

# Function to check if a port is in use and kill the process using it
check_port() {
    local port=$1
    if lsof -i :$port &> /dev/null; then
        echo "Port $port is in use. Killing process..."
        kill $(lsof -t -i:$port)
        sleep 1
    fi
}

# Start FastAPI backend in background
check_port 8000
echo "Starting FastAPI backend..."
python main.py &
API_PID=$!
sleep 3  # Give API time to start

# Check if API started successfully
if ! curl -s http://localhost:8000/ > /dev/null; then
    echo "Error: FastAPI backend failed to start"
    cleanup
fi

echo "FastAPI backend is running on http://localhost:8000"

# Start Gradio Web Interface in background
check_port 7860
echo "Starting Gradio Web Interface..."
python ui/gradio_interface.py &
GRADIO_PID=$!
sleep 5  # Give Web Interface time to start

echo "Gradio UI is running on http://localhost:7860"

# Start Translation Workers in background
echo "Starting Translation Workers..."
echo "Press Ctrl+C to stop all services"
for i in {1..4}; do
  python workers/worker.py &
  WORKER_PIDS+=($!)
done

# Wait for all background processes
echo "All services started. Waiting for termination signal..."
wait 