import os
import pickle
from pathlib import Path
from typing import Any, List, Optional

import faiss
import numpy as np

from chatbot.embedding import EmbeddingPipeline, embed_text


class FaissVectorStore:
    """
    FAISS vector store backed strictly by the SentenceTransformers microservice (all-MiniLM-L6-v2).
    Generates 384-dimensional normalized vectors.
    """

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        embedding_dims: Optional[int] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        **kwargs,
    ):
        # Resolve persist directory (supports EFS mount via FAISS_PERSIST_DIR)
        target_dir = persist_dir or os.getenv("FAISS_PERSIST_DIR", "faiss_store")
        persist_path = Path(target_dir)
        if not persist_path.is_absolute():
            project_root = Path(__file__).resolve().parent.parent.parent
            persist_path = project_root / target_dir
        self.persist_dir = str(persist_path.resolve())
        os.makedirs(self.persist_dir, exist_ok=True)

        self.embedding_dims = embedding_dims or int(os.getenv("EMBEDDING_DIMS", "384"))
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.index = None
        self.metadata: List[Any] = []
        self.last_loaded_mtime: float = 0.0

        print(f"[INFO] Vector store embedding dims: {self.embedding_dims}")
        print(f"[INFO] Vector store directory     : {self.persist_dir}")

    # ------------------------------------------------------------------
    # Build / Add
    # ------------------------------------------------------------------

    def build_from_documents(self, documents: List[Any]):
        if not documents:
            print("[WARN] No documents provided to build vector store.")
            return

        print(f"[INFO] Building vector store from {len(documents)} raw documents...")
        pipeline = EmbeddingPipeline(
            dimensions=self.embedding_dims,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        chunks = pipeline.chunk_documents(documents)
        if not chunks:
            print("[WARN] No chunks generated from documents.")
            return

        embeddings = pipeline.embed_chunks(chunks)
        metadatas = [{"text": chunk.page_content} for chunk in chunks]

        # Reset to ensure a clean rebuild
        self.index = None
        self.metadata = []
        self.add_embeddings(np.array(embeddings, dtype="float32"), metadatas)
        self.save()
        print(f"[INFO] Vector store built and saved to {self.persist_dir}")

    def add_documents(self, documents: List[Any]):
        """Incrementally embed and add documents into the existing FAISS index."""
        if not documents:
            print("[WARN] No documents provided to add_documents.")
            return

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
        print(f"[INFO] Added {len(chunks)} chunks to vector store.")

    def add_embeddings(self, embeddings: np.ndarray, metadatas: List[Any]):
        embeddings = embeddings.astype("float32")
        if self.index is None:
            self.index = faiss.IndexFlatL2(embeddings.shape[1])
            print(f"[INFO] Created new FAISS IndexFlatL2 (dims={embeddings.shape[1]})")
        self.index.add(embeddings)
        self.metadata.extend(metadatas)
        print(f"[INFO] Index now contains {self.index.ntotal} vectors.")

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------

    def save(self):
        faiss_path = os.path.join(self.persist_dir, "faiss.index")
        meta_path = os.path.join(self.persist_dir, "metadata.pkl")
        faiss.write_index(self.index, faiss_path)
        with open(meta_path, "wb") as f:
            pickle.dump(self.metadata, f)
        print(f"[INFO] Saved FAISS index ({self.index.ntotal} vectors) to {self.persist_dir}")

    def load(self) -> bool:
        faiss_path = os.path.join(self.persist_dir, "faiss.index")
        meta_path = os.path.join(self.persist_dir, "metadata.pkl")
        if not os.path.exists(faiss_path) or not os.path.exists(meta_path):
            print(f"[WARN] No saved index found in {self.persist_dir}")
            return False
        try:
            self.index = faiss.read_index(faiss_path)
            with open(meta_path, "rb") as f:
                self.metadata = pickle.load(f)
            self.last_loaded_mtime = max(
                os.path.getmtime(faiss_path), os.path.getmtime(meta_path)
            )
            print(f"[INFO] Loaded FAISS index with {self.index.ntotal} vectors (dims={self.index.d}).")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load FAISS index: {e}")
            return False

    def reload_if_updated(self) -> bool:
        """Reload the index if another worker updated the shared EFS volume."""
        faiss_path = os.path.join(self.persist_dir, "faiss.index")
        meta_path = os.path.join(self.persist_dir, "metadata.pkl")
        if not os.path.exists(faiss_path) or not os.path.exists(meta_path):
            return False
        try:
            current_mtime = max(
                os.path.getmtime(faiss_path), os.path.getmtime(meta_path)
            )
            if current_mtime > self.last_loaded_mtime:
                print(f"[INFO] Detected updated vector store on EFS. Reloading...")
                return self.load()
        except Exception as e:
            print(f"[WARN] Failed to check vector store mtime: {e}")
        return False

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query_embedding: np.ndarray, top_k: int = 5) -> List[dict]:
        self.reload_if_updated()
        if self.index is None:
            print("[WARN] FAISS index is not initialized or loaded.")
            return []
        if query_embedding.ndim == 1:
            query_embedding = np.expand_dims(query_embedding, axis=0)
        D, I = self.index.search(query_embedding, top_k)
        results = []
        for idx, dist in zip(I[0], D[0]):
            meta = self.metadata[idx] if 0 <= idx < len(self.metadata) else None
            results.append({"index": idx, "distance": dist, "metadata": meta})
        return results

    def query(self, query_text: str, top_k: int = 5) -> List[dict]:
        """Embed query_text via SentenceTransformers microservice and run FAISS search."""
        vec = embed_text(query_text)
        query_emb = np.array([vec], dtype="float32")
        return self.search(query_emb, top_k=top_k)
