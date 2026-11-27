import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, List, Optional

import numpy as np
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Load environment from consumer/.env
_here = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_here / ".env")
load_dotenv()

# Dedicated SentenceTransformers microservice URL
EMBEDDING_SERVICE_URL = os.getenv("EMBEDDING_SERVICE_URL", "http://localhost:8001").rstrip("/")
DEFAULT_EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMS", "384"))


def _embed_batch_via_service(texts: List[str]) -> List[List[float]]:
    """
    Call the standalone SentenceTransformers microservice for a batch of text chunks.
    Raises RuntimeError if the microservice is offline or unreachable.
    """
    if not EMBEDDING_SERVICE_URL:
        raise RuntimeError(
            "[ERROR] EMBEDDING_SERVICE_URL is not configured in consumer/.env. "
            "The system strictly uses the SentenceTransformers microservice."
        )

    url = f"{EMBEDDING_SERVICE_URL}/embed"
    payload = json.dumps({"texts": texts, "normalize": True}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["embeddings"]
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"[FATAL] Cannot connect to Embedding Microservice at '{url}'. "
            f"Ensure the 'services/embedding-service' container is running on port 8001. Error: {e}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"[ERROR] Failed calling embedding service at {url}: {e}") from e


def _embed_single_via_service(text: str) -> List[float]:
    """
    Call the standalone SentenceTransformers microservice for a single string.
    """
    if not EMBEDDING_SERVICE_URL:
        raise RuntimeError("[ERROR] EMBEDDING_SERVICE_URL is not configured in consumer/.env.")

    url = f"{EMBEDDING_SERVICE_URL}/embed-single"
    payload = json.dumps({"text": text, "normalize": True}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["embedding"]
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"[FATAL] Cannot connect to Embedding Microservice at '{url}'. "
            f"Ensure 'services/embedding-service' is running. Error: {e}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"[ERROR] Failed calling embedding service at {url}: {e}") from e


def embed_text(text: str) -> List[float]:
    """Embed a single text string using the SentenceTransformers microservice."""
    return _embed_single_via_service(text)


class EmbeddingPipeline:
    """
    Text chunker + Embedding pipeline for consumer worker.
    Exclusively communicates with the standalone SentenceTransformers microservice.
    No AWS Bedrock embedding model is used.
    """

    def __init__(
        self,
        dimensions: Optional[int] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        batch_size: int = 64,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.batch_size = batch_size
        self.dimensions = dimensions or DEFAULT_EMBEDDING_DIMS

        print(f"[INFO] [Consumer Pipeline] Target Embedding Microservice: {EMBEDDING_SERVICE_URL} ({self.dimensions} dims)")

    def chunk_documents(self, documents: List[Any]) -> List[Any]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", " ", ""],
        )
        chunks = splitter.split_documents(documents)
        print(f"[INFO] [Consumer Pipeline] Split {len(documents)} document(s) into {len(chunks)} chunks.")
        return chunks

    def embed_chunks(self, chunks: List[Any]) -> np.ndarray:
        texts = [chunk.page_content for chunk in chunks]
        total = len(texts)
        if total == 0:
            return np.empty((0, self.dimensions), dtype="float32")

        print(f"[INFO] [Consumer Pipeline] Sending {total} chunks to embedding microservice in batches of {self.batch_size}...")
        all_embeddings: List[List[float]] = []

        for i in range(0, total, self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_vecs = _embed_batch_via_service(batch)
            all_embeddings.extend(batch_vecs)
            print(f"[INFO] [Consumer Pipeline] ... embedded {min(i + self.batch_size, total)}/{total} chunks")

        arr = np.array(all_embeddings, dtype="float32")
        print(f"[INFO] [Consumer Pipeline] Completed! Generated embeddings shape: {arr.shape}")
        return arr
