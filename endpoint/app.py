"""
FastAPI endpoint — POST /chat -> {"response": "...", "sources": [...]}

Run locally:
    uvicorn endpoint.app:app --reload --port 8000

Then test:
    curl -X POST http://localhost:8000/chat -H 'Content-Type: application/json' \\
         -d '{"message": "How often should I get antenatal check-ups?"}'
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .llm import generate_answer, safety_prefilter
from .rag import RagIndex

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("endpoint")

app = FastAPI(
    title="Maternal & Child Health Q&A",
    description=(
        "Small India-focused maternal and child health Q&A endpoint built as "
        "the live target for the CeRAI evaluation-tool assignment. "
        "Backed by Groq Llama-3.3-70b + tiny FAISS RAG over WHO/UNICEF/MoHFW docs."
    ),
    version="0.1.0",
)

# --- RAG lifecycle (lazy-loaded; index is read once at first request) -------

_index: RagIndex | None = None


def _get_index() -> RagIndex | None:
    global _index
    if _index is not None:
        return _index
    index_dir = Path(os.environ.get("RAG_INDEX_DIR", "endpoint/index"))
    if not (index_dir / "faiss.index").exists():
        logger.warning(
            "No index found at %s — endpoint will answer WITHOUT RAG. "
            "Run `python -m endpoint.build_index` first.",
            index_dir,
        )
        return None
    idx = RagIndex(
        embedding_model=os.environ.get(
            "RAG_EMBEDDING_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ),
        index_dir=index_dir,
    )
    idx.load()
    _index = idx
    return idx


# --- request / response schemas ---------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class Source(BaseModel):
    doc_id: str
    chunk_id: int
    score: float


class ChatResponse(BaseModel):
    response: str
    sources: list[Source] = Field(default_factory=list)
    safety_action: str = Field(
        default="none",
        description="One of: 'none' | 'hard_refuse' | 'deflect'. Tells evaluator what happened.",
    )


# --- routes ------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return """
    <html><body style="font-family: sans-serif; max-width: 700px; margin: 2rem auto; padding: 0 1rem;">
      <h2>Maternal &amp; Child Health Q&amp;A</h2>
      <p>POST a JSON body <code>{"message": "..."}</code> to <code>/chat</code> to ask a question.</p>
      <p>See <a href="/docs">/docs</a> for the interactive Swagger UI.</p>
      <p>This endpoint is the live target for a CeRAI evaluation-tool assignment.
         Source on GitHub.</p>
    </body></html>
    """


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="empty message")

    # ---- safety pre-filter ----
    decision = safety_prefilter(message)
    if decision.block:
        action = "hard_refuse" if decision.reason.startswith("hard_refuse") else "deflect"
        logger.info("Safety pre-filter blocked: %s", decision.reason)
        return ChatResponse(
            response=decision.response or "",
            sources=[],
            safety_action=action,
        )

    # ---- retrieve ----
    idx = _get_index()
    sources: list[Source] = []
    context_chunks: list[str] = []
    if idx is not None:
        top_k = int(os.environ.get("RAG_TOP_K", "4"))
        hits = idx.search(message, top_k=top_k)
        for chunk, score in hits:
            sources.append(Source(doc_id=chunk.doc_id, chunk_id=chunk.chunk_id, score=score))
            context_chunks.append(f"[{chunk.doc_id}#{chunk.chunk_id}] {chunk.text}")

    # ---- generate ----
    try:
        answer = generate_answer(message, context_chunks)
    except RuntimeError as e:
        # GROQ_API_KEY missing → fail loud, NOT silent empty (contrast CeRAI).
        raise HTTPException(status_code=503, detail=str(e)) from e

    return ChatResponse(response=answer, sources=sources, safety_action="none")
