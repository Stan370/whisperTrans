#!/bin/bash

# Refactored Multilingual Story Translation System Startup Script

# Function to check if a command exists
check_command() {
    if ! command -v $1 &> /dev/null; then
        echo "Error: $1 is not installed"
        exit 1
    fi
}

# Function to cleanup background processes
cleanup() {
    echo "Shutting down services..."
    pkill -f "python api/main.py" 2>/dev/null
    pkill -f "python ui/gradio_interface.py" 2>/dev/null
    pkill -f "python workers/worker.py" 2>/dev/null
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

# Start FastAPI backend in background
echo "Starting FastAPI backend..."
python api/main.py &
API_PID=$!
sleep 5  # Give API time to start

# Check if API started successfully
if ! curl -s http://localhost:8000/ > /dev/null; then
    echo "Error: FastAPI backend failed to start"
    cleanup
fi

echo "FastAPI backend is running on http://localhost:8000"

# Start Gradio Web Interface in background
echo "Starting Gradio Web Interface..."
python ui/gradio_interface.py &
GRADIO_PID=$!
sleep 5  # Give Web Interface time to start

echo "Gradio UI is running on http://localhost:7860"

# Start Translation Worker (in foreground)
echo "Starting Translation Worker..."
echo "Press Ctrl+C to stop all services"
python workers/worker.py

# Note: The script will keep running until the translation worker is stopped 