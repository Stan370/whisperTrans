# syntax=docker/dockerfile:1
#
# Multi-stage build to minimize the final image size.
#
# Stage 1 (builder): Install all build-time deps (gcc, torch, etc.)
#                    in a throwaway layer.
# Stage 2 (runtime): Copy only the installed packages, no build tools.
#                    Saves ~300-500MB by dropping gcc, python3-dev, pip cache.

# ─── Stage 1: Builder ─────────────────────────────────────────────────────────
FROM python:3.10-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install torch CPU separately first so Docker layer cache prevents re-downloading
# 2.5GB on every code change (only re-runs if requirements.txt changes).
RUN pip install --no-cache-dir \
    torch==2.1.0 \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
# Remove torch from requirements to avoid double-installing it
RUN grep -v "^torch" requirements.txt > requirements_notorch.txt && \
    pip install --no-cache-dir -r requirements_notorch.txt

# ─── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.10-slim AS runtime

# Only runtime system libs (no gcc/python3-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed Python packages from builder (avoids reinstalling)
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create required directories
RUN mkdir -p temp/uploads temp/results logs

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
EXPOSE 8000 7860