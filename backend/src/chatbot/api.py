from contextlib import asynccontextmanager
from pathlib import Path
import shutil
from typing import List, Literal

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from chatbot.search import RAGSearch
from chatbot.s3_service import get_s3_service
from chatbot.data_loader import load_documents_from_paths

SYSTEM_PROMPT = """You are a friendly, exam-focused tutor for students preparing for the SSC CGL exam.
Current subject in the knowledge base: History.

Rules:
- Answer ONLY from the provided context. If the context does not contain the answer, say so clearly and do not invent facts.
- Keep answers clear and revision-friendly: a short explanation, then key points (dates, names, places, causes/effects) as bullets.
- Use simple language. Use markdown for formatting.
- For follow-up questions, use the earlier conversation for meaning, but facts must still come from the context."""

MAX_HISTORY_TURNS = 6  # last N messages sent back to the LLM

state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Loads the embedding model + FAISS index once at startup (builds the index from S3/data if missing).
    state["rag"] = RAGSearch()
    yield
    state.clear()


app = FastAPI(title="SSC CGL RAG Chatbot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    top_k: int = Field(4, ge=1, le=10)
    history: List[HistoryMessage] = []


class Source(BaseModel):
    text: str
    distance: float  # FAISS L2 distance: lower = closer match


class ChatResponse(BaseModel):
    answer: str
    sources: List[Source]


@app.get("/health")
def health():
    rag = state.get("rag")
    has_index = rag is not None and rag.vectorstore.index is not None
    vector_count = len(rag.vectorstore.metadata) if (rag and rag.vectorstore.metadata) else 0
    return {
        "status": "ok" if rag else "starting",
        "index_ready": has_index,
        "vector_count": vector_count,
    }


@app.get("/documents")
def list_documents():
    """
    List all documents currently stored in the AWS S3 knowledge base bucket.
    """
    try:
        s3 = get_s3_service()
        docs = s3.list_documents()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch documents from S3: {str(e)}",
        )

    total_size = sum(d["size_bytes"] for d in docs)
    rag = state.get("rag")
    vector_count = len(rag.vectorstore.metadata) if (rag and rag.vectorstore.metadata) else 0

    return {
        "documents": docs,
        "total_files": len(docs),
        "total_size_bytes": total_size,
        "vector_count": vector_count,
        "s3_bucket": s3.bucket_name,
    }


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a document. The file is stored in AWS S3 (via boto3) and cached locally for indexing.
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    allowed_extensions = {".pdf", ".txt", ".csv", ".xlsx", ".docx", ".json"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed types: {', '.join(sorted(allowed_extensions))}",
        )

    safe_filename = Path(file.filename).name
    destination = data_dir / safe_filename

    # 1. Save locally
    try:
        with destination.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file locally: {str(e)}")

    size_bytes = destination.stat().st_size

    # 2. Upload to S3 using boto3
    try:
        s3 = get_s3_service()
        s3.upload_file(destination, safe_filename)
    except Exception as e:
        # Clean up local file if S3 upload fails
        if destination.exists():
            destination.unlink()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload '{safe_filename}' to S3: {str(e)}",
        )

    return {
        "status": "success",
        "filename": safe_filename,
        "size_bytes": size_bytes,
        "s3_bucket": s3.bucket_name,
        "message": f"'{safe_filename}' uploaded to S3 bucket '{s3.bucket_name}' successfully.",
    }


@app.post("/rebuild-vectorstore")
def rebuild_vectorstore():
    """
    Sync all files from AWS S3 storage, parse documents, and rebuild the vector store.
    """
    rag = state.get("rag")
    if rag is None:
        raise HTTPException(status_code=503, detail="RAG system is not initialized.")

    project_root = Path(__file__).resolve().parent.parent.parent
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Sync files from S3 bucket to local repository directory
    try:
        s3 = get_s3_service()
        synced_files = s3.sync_s3_to_local(data_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync documents from S3: {str(e)}")

    if not synced_files:
        raise HTTPException(
            status_code=400,
            detail=f"No documents found in S3 bucket '{s3.bucket_name}' to index. Upload documents first.",
        )

    # 2. Load and parse the synced S3 documents
    try:
        docs = load_documents_from_paths(synced_files)
        if not docs:
            raise HTTPException(
                status_code=400,
                detail="No readable content found in synced S3 documents to index.",
            )

        # 3. Build and persist FAISS index
        rag.vectorstore.build_from_documents(docs)
        vector_count = len(rag.vectorstore.metadata) if rag.vectorstore.metadata else 0
        return {
            "status": "success",
            "message": f"Vector store successfully synced and rebuilt from S3 ({len(synced_files)} files).",
            "document_count": len(docs),
            "vector_count": vector_count,
            "s3_bucket": s3.bucket_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rebuild vector store: {str(e)}")


@app.post("/process-sqs-jobs")
def process_sqs_jobs(max_messages: int = 5):
    """
    Polls the SQS queue for newly uploaded files from Lambda/S3,
    downloads and indexes them incrementally into the vector database.
    """
    from chatbot.sqs_consumer import SQSConsumer

    rag = state.get("rag")
    vectorstore = rag.vectorstore if rag else None

    consumer = SQSConsumer(vectorstore=vectorstore)
    processed = consumer.poll_messages(max_messages=max_messages, wait_time_seconds=5)

    # Reload vectorstore into memory if new items were indexed
    if processed > 0 and rag:
        rag.vectorstore.load()

    total_vectors = len(rag.vectorstore.metadata) if (rag and rag.vectorstore.metadata) else 0

    return {
        "status": "success",
        "processed_jobs": processed,
        "total_vectors": total_vectors,
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    rag = state.get("rag")
    if rag is None:
        raise HTTPException(status_code=503, detail="Model is still loading, try again shortly.")
    if rag.vectorstore.index is None:
        raise HTTPException(status_code=503, detail="Vector store is empty. Add files to S3 and rebuild.")

    results = rag.vectorstore.query(req.message, top_k=req.top_k)
    hits = [r for r in results if r["metadata"] and r["metadata"].get("text")]
    if not hits:
        return ChatResponse(answer="I couldn't find anything relevant in the study material.", sources=[])

    context = "\n\n---\n\n".join(h["metadata"]["text"] for h in hits)

    messages = [("system", SYSTEM_PROMPT)]
    for m in req.history[-MAX_HISTORY_TURNS:]:
        messages.append(("human" if m.role == "user" else "ai", m.content))
    messages.append(("human", f"Context:\n{context}\n\nQuestion: {req.message}"))

    try:
        response = rag.llm.invoke(messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    sources = [
        Source(text=h["metadata"]["text"][:400], distance=float(h["distance"])) for h in hits
    ]
    return ChatResponse(answer=response.content, sources=sources)
