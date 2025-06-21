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

# Start Translation Worker (in foreground)
echo "Starting Translation Worker..."
echo "Press Ctrl+C to stop all services"
for i in {1..4}; do
  python workers/worker.py &
done