import os
import faiss
import numpy as np
import pickle
from pathlib import Path
from typing import List, Any
from sentence_transformers import SentenceTransformer
from chatbot.embedding import EmbeddingPipeline

class FaissVectorStore:
    def __init__(self, persist_dir: str = "faiss_store", embedding_model: str = "all-MiniLM-L6-v2", chunk_size: int = 1000, chunk_overlap: int = 200):
        # Always resolve relative persist_dir to project root (parallel to src/)
        persist_path = Path(persist_dir)
        if not persist_path.is_absolute():
            project_root = Path(__file__).resolve().parent.parent.parent
            persist_path = project_root / persist_dir
        self.persist_dir = str(persist_path.resolve())
        os.makedirs(self.persist_dir, exist_ok=True)

        self.index = None
        self.metadata = []
        self.embedding_model = embedding_model
        self.model = SentenceTransformer(embedding_model)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        print(f"[INFO] Loaded embedding model: {embedding_model}")
        print(f"[INFO] Vector store directory: {self.persist_dir}")

    def build_from_documents(self, documents: List[Any]):
        if not documents:
            print("[WARN] No documents provided to build vector store.")
            return

        print(f"[INFO] Building vector store from {len(documents)} raw documents...")
        emb_pipe = EmbeddingPipeline(model_name=self.embedding_model, chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap)
        chunks = emb_pipe.chunk_documents(documents)
        if not chunks:
            print("[WARN] No chunks generated from documents.")
            return

        embeddings = emb_pipe.embed_chunks(chunks)
        metadatas = [{"text": chunk.page_content} for chunk in chunks]
        self.add_embeddings(np.array(embeddings).astype('float32'), metadatas)
        self.save()
        print(f"[INFO] Vector store built and saved to {self.persist_dir}")

    def add_embeddings(self, embeddings: np.ndarray, metadatas: List[Any] = None):
        if embeddings is None or embeddings.size == 0:
            print("[WARN] No embeddings provided to add to Faiss index.")
            return

        if embeddings.ndim == 1:
            embeddings = np.expand_dims(embeddings, axis=0)

        dim = embeddings.shape[1]
        if self.index is None:
            self.index = faiss.IndexFlatL2(dim)
        self.index.add(embeddings)
        if metadatas:
            self.metadata.extend(metadatas)
        print(f"[INFO] Added {embeddings.shape[0]} vectors to Faiss index.")

    def save(self):
        if self.index is None:
            print(f"[WARN] No index to save to {self.persist_dir}")
            return
        faiss_path = os.path.join(self.persist_dir, "faiss.index")
        meta_path = os.path.join(self.persist_dir, "metadata.pkl")
        faiss.write_index(self.index, faiss_path)
        with open(meta_path, "wb") as f:
            pickle.dump(self.metadata, f)
        print(f"[INFO] Saved Faiss index and metadata to {self.persist_dir}")

    def load(self) -> bool:
        faiss_path = os.path.join(self.persist_dir, "faiss.index")
        meta_path = os.path.join(self.persist_dir, "metadata.pkl")
        
        # Check if both required files exist before loading
        if not os.path.exists(faiss_path) or not os.path.exists(meta_path):
            print(f"[WARN] Vector store files not found in '{self.persist_dir}'. Skipping load.")
            return False

        try:
            self.index = faiss.read_index(faiss_path)
            with open(meta_path, "rb") as f:
                self.metadata = pickle.load(f)
            print(f"[INFO] Loaded Faiss index and metadata from {self.persist_dir}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load vector store: {e}")
            return False

    def search(self, query_embedding: np.ndarray, top_k: int = 5):
        if self.index is None:
            print("[WARN] Faiss index is not initialized or loaded.")
            return []
        if query_embedding.ndim == 1:
            query_embedding = np.expand_dims(query_embedding, axis=0)
        D, I = self.index.search(query_embedding, top_k)
        results = []
        for idx, dist in zip(I[0], D[0]):
            meta = self.metadata[idx] if 0 <= idx < len(self.metadata) else None
            results.append({"index": idx, "distance": dist, "metadata": meta})
        return results

    def query(self, query_text: str, top_k: int = 5):
        print(f"[INFO] Querying vector store for: '{query_text}'")
        query_emb = self.model.encode([query_text]).astype('float32')
        return self.search(query_emb, top_k=top_k)

# Example usage
if __name__ == "__main__":
    from chatbot.data_loader import load_all_documents
    docs = load_all_documents("data")
    store = FaissVectorStore("faiss_store")
    store.build_from_documents(docs)
    store.load()
    print(store.query("What is attention mechanism?", top_k=3))
