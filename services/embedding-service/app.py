import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

# Load environment variables strictly from services/embedding-service/.env
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path)
load_dotenv()

MODEL_NAME = os.getenv("MODEL_NAME", "all-MiniLM-L6-v2")

app = FastAPI(
    title="High-Speed Embedding Microservice",
    description="Standalone Sentence-Transformers embedding API for RAG ingestion & querying",
    version="1.0.0",
)

# Load model once at startup into memory
print(f"[INFO] Initializing embedding model: {MODEL_NAME}...")
model = SentenceTransformer(MODEL_NAME)
embedding_dim = model.get_embedding_dimension()
print(f"[INFO] Model '{MODEL_NAME}' successfully loaded! Vector dimensions: {embedding_dim}")


class EmbedBatchRequest(BaseModel):
    texts: List[str] = Field(..., description="List of text chunks to embed", min_length=1)
    normalize: bool = Field(True, description="Whether to L2-normalize vectors")


class EmbedSingleRequest(BaseModel):
    text: str = Field(..., description="Single text query to embed", min_length=1)
    normalize: bool = Field(True, description="Whether to L2-normalize vectors")


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]
    dimensions: int
    count: int
    model: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "dimensions": embedding_dim,
    }


@app.post("/embed", response_model=EmbedResponse)
def embed_batch(req: EmbedBatchRequest):
    """
    Generate vector embeddings for a batch of text chunks.
    Processes efficiently using batch_size=64.
    """
    if not req.texts:
        raise HTTPException(status_code=400, detail="Empty texts array")

    try:
        vectors = model.encode(
            req.texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=req.normalize,
            convert_to_numpy=True,
        )
        return EmbedResponse(
            embeddings=vectors.tolist(),
            dimensions=embedding_dim,
            count=len(req.texts),
            model=MODEL_NAME,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {str(e)}")


@app.post("/embed-single")
def embed_single(req: EmbedSingleRequest):
    """
    Generate embedding for a single text string (optimized for user search queries).
    """
    try:
        vector = model.encode(
            req.text,
            normalize_embeddings=req.normalize,
            convert_to_numpy=True,
        )
        return {
            "embedding": vector.tolist(),
            "dimensions": embedding_dim,
            "model": MODEL_NAME,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {str(e)}")
