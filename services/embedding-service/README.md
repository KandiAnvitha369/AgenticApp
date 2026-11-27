# High-Speed Embedding Microservice

Standalone microservice providing fast text embeddings using `sentence-transformers` (`all-MiniLM-L6-v2`) on CPU. Designed to be deployed as a separate ECS service or sidecar.

## Why this service?
1. **No AWS Bedrock Rate Limits**: Embeds thousands of text chunks in seconds with zero `ThrottlingException` or 429 errors.
2. **Lean Main Backend**: Keeps the main backend container small (~1.5GB) by keeping PyTorch out of it.
3. **Optimized Size**: Uses CPU-only PyTorch wheels (`--extra-index-url https://download.pytorch.org/whl/cpu`), so this image is only ~1.2 GB (instead of 6GB+ with CUDA).

---

## API Endpoints

- `GET /health` - Health check (reports model name, dimensions)
- `POST /embed` - Batch embedding
  ```json
  {
    "texts": ["First chunk of text", "Second chunk of text"],
    "normalize": true
  }
  ```
  Returns:
  ```json
  {
    "embeddings": [[...], [...]],
    "dimensions": 384,
    "count": 2,
    "model": "all-MiniLM-L6-v2"
  }
  ```
- `POST /embed-single` - Single text embedding (optimized for query search)
  ```json
  {
    "text": "What is the capital of France?",
    "normalize": true
  }
  ```

---

## Running Locally

```powershell
cd services\embedding-service
uvicorn app:app --host 0.0.0.0 --port 8001
```

---

## Building & Pushing Docker Image to AWS ECR

```bash
# 1. Authenticate Docker with your ECR registry
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin 377074487303.dkr.ecr.ap-southeast-2.amazonaws.com

# 2. Create ECR repository (if not already created)
aws ecr create-repository --repository-name rag-chatbot-embedding --region ap-southeast-2

# 3. Build Docker image
cd services/embedding-service
docker build -t rag-chatbot-embedding:latest .

# 4. Tag and Push to ECR
docker tag rag-chatbot-embedding:latest 377074487303.dkr.ecr.ap-southeast-2.amazonaws.com/rag-chatbot-embedding:latest
docker push 377074487303.dkr.ecr.ap-southeast-2.amazonaws.com/rag-chatbot-embedding:latest
```

---

## Connecting Backend to this Service

In your `backend/.env` (or ECS environment variables):
```ini
# Local
EMBEDDING_SERVICE_URL=http://localhost:8001

# ECS Sidecar in same task
EMBEDDING_SERVICE_URL=http://127.0.0.1:8001

# Standalone ECS Service via AWS Cloud Map
EMBEDDING_SERVICE_URL=http://rag-chatbot-embedding.local:8001
```
