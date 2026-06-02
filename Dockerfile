# syntax=docker/dockerfile:1
FROM python:3.10-slim

# System deps required by faster-whisper and torch audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install torch CPU first (keeps layer cache efficient and avoids re-downloading 2GB on every build)
RUN pip install --no-cache-dir \
    torch==2.1.0 \
    torchaudio==2.1.0 \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create temp directories expected by the application
RUN mkdir -p temp/uploads temp/results logs

# Default entrypoint is the API; override in K8s Deployment command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

EXPOSE 8000 7860