"""
FastAPI layer on top of the existing RAG pipeline (RAGSearch -> FaissVectorStore + Groq LLM).
Existing files are untouched; this only imports them.

Run (from the src/ folder):
    uvicorn chatbot.api:app --reload --port 8000
"""
from contextlib import asynccontextmanager
from typing import List, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from chatbot.search import RAGSearch

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
    # Loads the embedding model + FAISS index once at startup (builds the index from data/ if missing).
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
    return {"status": "ok" if rag else "starting"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    rag = state.get("rag")
    if rag is None:
        raise HTTPException(status_code=503, detail="Model is still loading, try again shortly.")
    if rag.vectorstore.index is None:
        raise HTTPException(status_code=503, detail="Vector store is empty. Add files to data/ and rebuild.")

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
