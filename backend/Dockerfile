# ==============================================================================
# Multi-Stage Optimized Dockerfile for SSC CGL RAG Chatbot (Backend)
#
# Embeddings + LLM: Amazon Bedrock (API calls) — no model weights in image.
# Stage 1 (builder): Compiles wheels, installs C/C++ build tools & pip deps
# Stage 2 (runner) : Minimal, secure, non-root runtime (~1.5GB vs 19GB before)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build Dependencies
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /build

# Install system build dependencies required for compiling native wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment to isolate all installed packages
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Layer cache optimization: copy requirements first to avoid reinstalling on source change
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Strip unneeded debug symbols and pre-compile bytecode to trim size
RUN find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true


# ------------------------------------------------------------------------------
# Stage 2: Final Lean Runtime Image
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS runner

WORKDIR /app

# Install ONLY runtime shared libraries needed by FAISS (no compilers)
# - libgomp1: OpenMP support required by faiss-cpu for multi-threaded vector search
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FAISS_PERSIST_DIR=/mnt/efs/faiss_store \
    BEDROCK_EMBEDDING_MODEL=amazon.titan-embed-text-v2:0 \
    BEDROCK_EMBEDDING_DIMS=512 \
    BEDROCK_LLM_MODEL=amazon.nova-lite-v1:0 \
    ENV=production

# Security: Create non-root system user and group
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/false -m appuser

# Pre-create writable mount & staging directories with proper permissions
RUN mkdir -p /mnt/efs/faiss_store /app/data/sqs_staging && \
    chown -R appuser:appgroup /mnt/efs/faiss_store /app/data

# Copy source code with non-root ownership
COPY --chown=appuser:appgroup src/ ./src/

# Switch to non-root user
USER appuser

EXPOSE 8000

# Health check for Application Load Balancer (ALB)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Default Command: Web API Server
# For SQS Worker Task, override CMD with: ["python", "-m", "chatbot.sqs_consumer"]
CMD ["uvicorn", "chatbot.api:app", "--host", "0.0.0.0", "--port", "8000"]
