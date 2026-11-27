# ==============================================================================
# Multi-Stage Optimized Dockerfile for Embedding Microservice
# Uses lightweight CPU-only PyTorch wheels (no 4GB+ CUDA bloat)
# Final image size: ~1.2 GB
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build Dependencies
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
# Install CPU-only torch + sentence-transformers without CUDA dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the default model into the image cache so cold starts are instant
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Strip bytecode caches
RUN find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true


# ------------------------------------------------------------------------------
# Stage 2: Minimal Runtime Image
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS runner

WORKDIR /app

# Copy virtualenv and cached HuggingFace model cache from builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /root/.cache /root/.cache

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MODEL_NAME=all-MiniLM-L6-v2 \
    PORT=8001

# Copy application source
COPY app.py .

EXPOSE 8001

HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
