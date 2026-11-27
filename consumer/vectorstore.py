import os
import pickle
from pathlib import Path
from typing import Any, List, Optional

import faiss
import numpy as np

try:
    from consumer.embedding import EmbeddingPipeline, embed_text
except ImportError:
    from embedding import EmbeddingPipeline, embed_text


class FaissVectorStore:
    """
    Self-contained FAISS vector store writer for the SQS consumer service.
    Directly persists vectors and metadata to EFS or local storage.
    Vectors are strictly 384-dimensional from SentenceTransformers microservice.
    """

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        embedding_dims: Optional[int] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        target_dir = persist_dir or os.getenv("FAISS_PERSIST_DIR", "faiss_store")
        persist_path = Path(target_dir)
        if not persist_path.is_absolute():
            repo_root = Path(__file__).resolve().parent.parent
            persist_path = repo_root / "backend" / target_dir
        self.persist_dir = str(persist_path.resolve())
        os.makedirs(self.persist_dir, exist_ok=True)

        self.embedding_dims = embedding_dims or int(os.getenv("EMBEDDING_DIMS", "384"))
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.index = None
        self.metadata: List[Any] = []
        self.last_loaded_mtime: float = 0.0

        print(f"[INFO] [Consumer VectorStore] Embedding dimensions: {self.embedding_dims}")
        print(f"[INFO] [Consumer VectorStore] Directory: {self.persist_dir}")

    def add_documents(self, documents: List[Any]):
        """Incrementally embed and add documents into the existing FAISS index."""
        if not documents:
            print("[WARN] [Consumer VectorStore] No documents provided to add_documents.")
            return

        if self.index is None:
            self.load()

        pipeline = EmbeddingPipeline(
            dimensions=self.embedding_dims,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        chunks = pipeline.chunk_documents(documents)
        if not chunks:
            return

        embeddings = pipeline.embed_chunks(chunks)
        metadatas = [{"text": chunk.page_content} for chunk in chunks]
        self.add_embeddings(np.array(embeddings, dtype="float32"), metadatas)
        self.save()
        print(f"[INFO] [Consumer VectorStore] Added {len(chunks)} chunks to vector store.")

    def add_embeddings(self, embeddings: np.ndarray, metadatas: List[Any]):
        embeddings = embeddings.astype("float32")
        if self.index is None:
            self.index = faiss.IndexFlatL2(embeddings.shape[1])
            print(f"[INFO] [Consumer VectorStore] Created new FAISS IndexFlatL2 (dims={embeddings.shape[1]})")
        self.index.add(embeddings)
        self.metadata.extend(metadatas)
        print(f"[INFO] [Consumer VectorStore] Index now contains {self.index.ntotal} vectors.")

    def save(self):
        os.makedirs(self.persist_dir, exist_ok=True)
        faiss_path = os.path.join(self.persist_dir, "faiss.index")
        meta_path = os.path.join(self.persist_dir, "metadata.pkl")
        faiss.write_index(self.index, faiss_path)
        with open(meta_path, "wb") as f:
            pickle.dump(self.metadata, f)
        print(f"[INFO] [Consumer VectorStore] Saved FAISS index ({self.index.ntotal} vectors) to {self.persist_dir}")

    def load(self) -> bool:
        faiss_path = os.path.join(self.persist_dir, "faiss.index")
        meta_path = os.path.join(self.persist_dir, "metadata.pkl")
        if not os.path.exists(faiss_path) or not os.path.exists(meta_path):
            print(f"[WARN] [Consumer VectorStore] No saved index found in {self.persist_dir}")
            return False
        try:
            self.index = faiss.read_index(faiss_path)
            with open(meta_path, "rb") as f:
                self.metadata = pickle.load(f)
            self.last_loaded_mtime = max(
                os.path.getmtime(faiss_path), os.path.getmtime(meta_path)
            )
            print(f"[INFO] [Consumer VectorStore] Loaded FAISS index with {self.index.ntotal} vectors (dims={self.index.d}).")
            return True
        except Exception as e:
            print(f"[ERROR] [Consumer VectorStore] Failed to load FAISS index: {e}")
            return False
