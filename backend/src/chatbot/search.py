import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_aws import ChatBedrock
from chatbot.vectorstore import FaissVectorStore

# Load backend environment variables
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)
load_dotenv()


class RAGSearch:
    """
    RAG search using:
      - Standalone SentenceTransformers microservice (all-MiniLM-L6-v2, 384 dims) for vector embeddings
      - Amazon Bedrock Nova Lite (or Groq/OpenAI) for LLM response generation ONLY
    """

    def __init__(
        self,
        persist_dir: str = None,
        embedding_dims: int = None,
        llm_model: str = None,
    ):
        resolved_dir = persist_dir or os.getenv("FAISS_PERSIST_DIR", "faiss_store")
        emb_dims = embedding_dims or int(os.getenv("EMBEDDING_DIMS", "384"))
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")

        self.vectorstore = FaissVectorStore(
            persist_dir=resolved_dir,
            embedding_dims=emb_dims,
        )

        # Load or build the FAISS index
        faiss_path = os.path.join(self.vectorstore.persist_dir, "faiss.index")
        meta_path = os.path.join(self.vectorstore.persist_dir, "metadata.pkl")
        if not (os.path.exists(faiss_path) and os.path.exists(meta_path)):
            try:
                from chatbot.s3_service import get_s3_service
                from chatbot.data_loader import load_documents_from_paths
                s3 = get_s3_service()
                project_root = Path(__file__).resolve().parent.parent.parent
                data_dir = project_root / "data"
                synced_files = s3.sync_s3_to_local(data_dir)
                if synced_files:
                    docs = load_documents_from_paths(synced_files)
                    self.vectorstore.build_from_documents(docs)
                else:
                    from chatbot.data_loader import load_all_documents
                    docs = load_all_documents("data")
                    if docs:
                        self.vectorstore.build_from_documents(docs)
            except Exception as e:
                print(f"[WARN] Failed to build vectorstore from S3/local at startup: {e}")
        else:
            self.vectorstore.load()

        # Bedrock LLM — used solely for text response generation
        model_id = llm_model or os.getenv("BEDROCK_LLM_MODEL", "amazon.nova-lite-v1:0")
        self.llm = ChatBedrock(
            model_id=model_id,
            region_name=region,
            model_kwargs={"temperature": 0.2, "max_tokens": 1024},
        )
        print(f"[INFO] Bedrock LLM initialized for text generation: {model_id} (region={region})")

    def search_and_summarize(self, query: str, top_k: int = 5) -> str:
        results = self.vectorstore.query(query, top_k=top_k)
        texts = [r["metadata"].get("text", "") for r in results if r["metadata"]]
        context = "\n\n".join(texts)
        if not context:
            return "No relevant documents found."
        prompt = (
            f"Summarize the following context for the query: '{query}'\n\n"
            f"Context:\n{context}\n\nSummary:"
        )
        response = self.llm.invoke([prompt])
        return response.content


if __name__ == "__main__":
    rag = RAGSearch()
    summary = rag.search_and_summarize("What is attention mechanism?", top_k=3)
    print("Summary:", summary)
