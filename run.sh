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

# Function to check if a port is in use and kill the process using it
check_port() {
    local port=$1
    if lsof -i :$port &> /dev/null; then
        echo "Port $port is in use. Killing process..."
        kill $(lsof -t -i:$port)
    fi
}

# Start FastAPI backend in background
check_port 8000
echo "Starting FastAPI backend..."
python api/main.py &
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

# Start Translation Worker (in foreground)
echo "Starting Translation Worker..."
echo "Press Ctrl+C to stop all services"
for i in {1..4}; do
  python workers/worker.py &
done
# Note: The script will keep running until the translation worker is stopped 