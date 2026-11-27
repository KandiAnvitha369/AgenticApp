# ==============================================================================
# Multi-Stage Optimized Dockerfile for Autonomous SQS Consumer Worker
#
# Listens to SQS queue, downloads files from S3, parses documents,
# generates embeddings (via embedding-service / Bedrock), and updates FAISS index on EFS.
#
# Build command (from project root):
#   docker build -f consumer/Dockerfile -t rag-chatbot-worker:latest .
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build Dependencies
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY consumer/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Strip bytecode caches
RUN find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true


# ------------------------------------------------------------------------------
# Stage 2: Final Lean Worker Image
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS runner

WORKDIR /app

# Install runtime shared library needed by faiss-cpu for multi-threaded vector search
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FAISS_PERSIST_DIR=/mnt/efs/faiss_store \
    ENV=production

# Security: Create non-root system user and group
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/false -m appuser

# Pre-create writable staging & vector store directories
RUN mkdir -p /mnt/efs/faiss_store /app/data/sqs_staging && \
    chown -R appuser:appgroup /mnt/efs/faiss_store /app/data

# Copy consumer worker module ONLY (completely decoupled from backend)
COPY --chown=appuser:appgroup consumer/ /app/consumer/

USER appuser

# Continuous SQS polling loop
CMD ["python", "-m", "consumer.sqs_consumer"]
