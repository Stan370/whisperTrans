# Multilingual Story Translation System - Refactored

## Overview

This is a completely refactored, distributed, fault-tolerant system for translating storybook audio and text into multiple languages. The system has been redesigned with proper separation of concerns, centralized configuration, and robust error handling.

## Architecture

### Core Components

1. **API Gateway (FastAPI)**
   - RESTful API endpoints
   - Request validation and routing
   - Health checks and monitoring

2. **Task Manager (Core Business Logic)**
   - Task creation and management
   - Redis Streams integration
   - Fault tolerance with PEL/XCLAIM

3. **Translation Service (Core Business Logic)**
   - STT processing with Whisper
   - Translation with Google Gemini 2.0 Flash
   - Text validation and WER calculation

4. **Worker Nodes (Standalone Processes)**
   - Distributed task processing
   - Resource monitoring
   - Heartbeat and health reporting

5. **Infrastructure Layer**
   - Redis client with connection pooling
   - Storage manager (local + S3)
   - Centralized configuration

6. **UI Layer (Gradio)**
   - Web interface for task management
   - Real-time status monitoring
   - System health dashboard

### Data Flow

```
[User] → [Gradio UI] → [FastAPI] → [Task Manager] → [Redis Streams] → [Worker] → [Translation Service]
                                                                                    ↓
[Results] ← [Task Manager] ← [Redis] ← [Worker] ← [Storage Manager]
```

## Key Improvements

### 1. **Eliminated Duplicate Code**
- Single implementation of each function across the system
- Centralized task management logic
- Unified Redis client with connection pooling
- Consistent error handling and logging

### 2. **Proper Separation of Concerns**
- **API Layer**: Only handles HTTP requests/responses
- **Core Layer**: Business logic for tasks and translation
- **Infrastructure Layer**: Data storage and external services
- **Worker Layer**: Standalone processing units
- **UI Layer**: User interface only

### 3. **Fault Tolerance**
- Redis Streams with consumer groups
- Pending Entries List (PEL) for failed tasks
- XCLAIM for task recovery from dead workers
- Automatic retry with configurable limits
- Health checks and resource monitoring

### 4. **Scalability**
- Separate worker processes/containers
- Resource-aware task scheduling
- Memory and CPU monitoring
- Horizontal scaling support

### 5. **Configuration Management**
- Environment-specific settings
- Centralized configuration with validation
- Support for development/staging/production

## Directory Structure

```
translation_system/
├── api/                    # API Gateway
│   ├── main.py            # FastAPI application
│   └── routes/
│       ├── tasks.py       # Task management endpoints
│       └── health.py      # Health check endpoints
├── core/                   # Business Logic
│   ├── models.py          # Data models
│   ├── task_manager.py    # Task management
│   └── translation_service.py  # Translation logic
├── infrastructure/         # Infrastructure Layer
│   ├── redis_client.py    # Redis client
│   └── storage.py         # File storage
├── workers/               # Worker Processes
│   └── worker.py          # Translation worker
├── utils/                 # Utilities
│   ├── config.py          # Configuration
│   └── logger.py          # Logging
├── ui/                    # User Interface
│   └── gradio_interface.py # Gradio web UI
├── config.py              # Main configuration
├── requirements.txt       # Dependencies
├── run_refactored.sh      # Startup script
└── README_REFACTORED.md   # This file
```

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Environment Configuration
Create a `.env` file:
```bash
# Required
GOOGLE_API_KEY=your_google_api_key_here

# Optional (with defaults)
ENVIRONMENT=development
REDIS_HOST=localhost
REDIS_PORT=6379
API_HOST=0.0.0.0
API_PORT=8000
```

### 3. Start Redis Server
```bash
redis-server
```

### 4. Start the System
```bash
# Option 1: Use the startup script
chmod +x run_refactored.sh
./run_refactored.sh

# Option 2: Start components manually
# Terminal 1: API
python api/main.py

# Terminal 2: UI
python ui/gradio_interface.py

# Terminal 3: Worker
python workers/worker.py
```

## API Endpoints

### Task Management
- `POST /api/v1/tasks/` - Create translation task
- `GET /api/v1/tasks/{task_id}` - Get task status
- `GET /api/v1/tasks/{task_id}/results` - Get task results
- `POST /api/v1/tasks/{task_id}/cancel` - Cancel task
- `POST /api/v1/tasks/{task_id}/retry` - Retry failed task
- `GET /api/v1/tasks/` - List all tasks
- `POST /api/v1/tasks/upload/zip` - Upload ZIP file

### Health & Monitoring
- `GET /api/v1/health/` - System health check
- `GET /api/v1/health/redis` - Redis health check
- `GET /api/v1/health/storage` - Storage health check
- `GET /api/v1/health/workers` - Worker status
- `GET /api/v1/health/system` - System resources
- `GET /api/v1/health/metrics` - System metrics

## Usage

### 1. Prepare Input Files
Create a ZIP file containing:
- **MP3 audio files** (e.g., `1.mp3`, `2.mp3`)
- **JSON file** with reference text:
```json
{
  "1": "Tilly, a little fox, loved her bright red balloon...",
  "2": "But one windy day, the balloon slipped away!..."
}
```

### 2. Upload and Translate
1. Open the Gradio UI (http://localhost:7860)
2. Upload your ZIP file
3. Select source and target languages
4. Submit and monitor the task
5. Download or view results when complete

### 3. Task Management
- Query task status by ID
- Cancel tasks
- Retry failed tasks
- List all tasks by status
- Monitor system health

## Configuration Options

### Environment Variables
- `ENVIRONMENT`: development/staging/production
- `DEBUG`: Enable debug mode
- `LOG_LEVEL`: Logging level (INFO/WARNING/ERROR)
- `WORKER_MEMORY_LIMIT`: Memory threshold for workers
- `TASK_RETRY_LIMIT`: Maximum retry attempts
- `WER_THRESHOLD`: Word Error Rate threshold

### File Processing
- **Audio Formats**: Only MP3 supported
- **Max File Size**: 100MB (configurable)
- **Storage**: Local filesystem or S3

### Translation
- **STT Model**: Whisper (base/medium/large)
- **Translation**: Google Gemini 2.0 Flash only
- **Languages**: English, Chinese, Japanese, Korean, French, German, Spanish

## Fault Tolerance Features

### 1. **Task Recovery**
- Failed workers are detected via heartbeat timeout
- Orphaned tasks are automatically claimed by healthy workers
- Tasks are retried up to the configured limit

### 2. **Resource Management**
- Memory usage monitoring
- CPU usage tracking
- Automatic task scheduling based on resource availability

### 3. **Data Persistence**
- Redis Streams for task queue
- Redis hashes for task metadata
- File storage for audio and results

### 4. **Health Monitoring**
- Worker heartbeat system
- System resource monitoring
- Service health checks
- Comprehensive metrics collection

## Deployment

### Development
```bash
./run_refactored.sh
```

### Production (Kubernetes)
```yaml
# Example deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: translation-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: translation-api
  template:
    metadata:
      labels:
        app: translation-api
    spec:
      containers:
      - name: api
        image: translation-api:latest
        ports:
        - containerPort: 8000
        env:
        - name: GOOGLE_API_KEY
          valueFrom:
            secretKeyRef:
              name: translation-secrets
              key: google-api-key
```

### Docker
```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["python", "api/main.py"]
```

## Monitoring and Logging

### Logging
- Structured logging with consistent format
- Environment-specific log levels
- File logging in production

### Metrics
- Task statistics (pending, processing, completed, failed)
- System resources (CPU, memory, disk)
- Worker status and performance
- API response times

### Health Checks
- Redis connectivity
- Storage availability
- Worker health
- System resources

## Troubleshooting

### Common Issues

1. **Redis Connection Failed**
   - Check if Redis server is running
   - Verify connection settings in config

2. **Worker Not Processing Tasks**
   - Check worker logs for errors
   - Verify system resources
   - Check Redis stream configuration

3. **Translation Failures**
   - Verify Google API key
   - Check network connectivity
   - Review error logs

4. **File Upload Issues**
   - Ensure files are MP3 format
   - Check file size limits
   - Verify storage permissions

### Debug Mode
Set `DEBUG=true` in environment to enable:
- Detailed error messages
- API documentation at `/docs`
- Verbose logging

## Migration from Old System

### Breaking Changes
- API endpoints have changed
- Only MP3 files supported
- Only Gemini translation provider
- New configuration system
- Different startup process

### Migration Steps
1. Update file formats to MP3
2. Update API calls to new endpoints
3. Set up new configuration
4. Use new startup script

## Contributing

1. Follow the established architecture
2. Add tests for new features
3. Update documentation
4. Use the centralized logging and configuration

## License

This project is licensed under the MIT License. 