"""
Tiny RAG: pull text from PDFs in ``endpoint/corpus/``, embed sentences,
store in a FAISS index. Retrieve top-K chunks at query time.

KEY DESIGN CHOICES:
- Local-only embeddings (sentence-transformers, no API call) — keeps the
  endpoint cheap and offline-capable. The Groq dependency is only for the
  final answer generation step.
- Multilingual embedding model so Hindi/English queries both hit relevant
  English-source chunks.
- Chunks are paragraph-sized (~512 chars). No fancy chunk-overlap tricks
  — the corpus is small, so retrieval recall is high already.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

_CHUNK_MAX_CHARS = 512


@dataclass
class Chunk:
    doc_id: str        # filename stem
    chunk_id: int      # ordinal within the doc
    text: str

    def to_json(self) -> dict:
        return {"doc_id": self.doc_id, "chunk_id": self.chunk_id, "text": self.text}

    @classmethod
    def from_json(cls, d: dict) -> "Chunk":
        return cls(doc_id=d["doc_id"], chunk_id=d["chunk_id"], text=d["text"])


def _split_into_chunks(text: str) -> list[str]:
    """Paragraph-based splitter with a hard cap on chunk size."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    for p in paragraphs:
        if len(p) <= _CHUNK_MAX_CHARS:
            out.append(p)
        else:
            # Long paragraph — sentence-split.
            sentences = re.split(r"(?<=[.!?])\s+", p)
            current = ""
            for s in sentences:
                if len(current) + len(s) + 1 > _CHUNK_MAX_CHARS:
                    if current:
                        out.append(current.strip())
                    current = s
                else:
                    current = f"{current} {s}".strip()
            if current:
                out.append(current.strip())
    return out


def _read_pdf(path: Path) -> str:
    """Extract text from a PDF using pypdf. Returns concatenated page text."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    texts: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        texts.append(page_text)
    return "\n\n".join(texts)


def _read_doc(path: Path) -> str:
    """Read .pdf, .txt, .md → plain text."""
    if path.suffix.lower() == ".pdf":
        return _read_pdf(path)
    return path.read_text(encoding="utf-8", errors="replace")


def load_chunks(corpus_dir: Path) -> list[Chunk]:
    """Walk corpus_dir, extract text, split into chunks."""
    chunks: list[Chunk] = []
    for path in sorted(corpus_dir.iterdir()):
        if path.suffix.lower() not in (".pdf", ".txt", ".md"):
            continue
        logger.info("Reading %s", path.name)
        text = _read_doc(path)
        for i, chunk_text in enumerate(_split_into_chunks(text)):
            chunks.append(Chunk(doc_id=path.stem, chunk_id=i, text=chunk_text))
    logger.info("Loaded %d chunks from %s", len(chunks), corpus_dir)
    return chunks


class RagIndex:
    """FAISS-backed index over Chunk objects."""

    def __init__(self, embedding_model: str, index_dir: Path) -> None:
        self.embedding_model_name = embedding_model
        self.index_dir = index_dir
        self._model = None       # lazy
        self._index = None       # lazy faiss index
        self._chunks: list[Chunk] = []

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model %s", self.embedding_model_name)
            self._model = SentenceTransformer(self.embedding_model_name)
        return self._model

    def build(self, chunks: list[Chunk]) -> None:
        import faiss
        import numpy as np

        if not chunks:
            raise ValueError("No chunks to index — corpus_dir is empty?")
        self._chunks = chunks
        texts = [c.text for c in chunks]
        emb = self._get_model().encode(texts, normalize_embeddings=True,
                                       convert_to_numpy=True, show_progress_bar=True)
        emb = emb.astype(np.float32)
        dim = emb.shape[1]
        index = faiss.IndexFlatIP(dim)  # cosine via normalized inner product
        index.add(emb)
        self._index = index

    def save(self) -> None:
        import faiss
        self.index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self.index_dir / "faiss.index"))
        (self.index_dir / "chunks.json").write_text(
            json.dumps([c.to_json() for c in self._chunks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (self.index_dir / "meta.json").write_text(
            json.dumps({"embedding_model": self.embedding_model_name}, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved index to %s", self.index_dir)

    def load(self) -> None:
        import faiss
        meta = json.loads((self.index_dir / "meta.json").read_text(encoding="utf-8"))
        if meta["embedding_model"] != self.embedding_model_name:
            logger.warning(
                "Index was built with %s but loading with %s — re-build recommended.",
                meta["embedding_model"], self.embedding_model_name,
            )
        self._index = faiss.read_index(str(self.index_dir / "faiss.index"))
        self._chunks = [Chunk.from_json(d) for d in json.loads(
            (self.index_dir / "chunks.json").read_text(encoding="utf-8")
        )]
        logger.info("Loaded %d chunks from index %s", len(self._chunks), self.index_dir)

    def search(self, query: str, top_k: int = 4) -> list[tuple[Chunk, float]]:
        import numpy as np

        if self._index is None:
            self.load()
        emb = self._get_model().encode([query], normalize_embeddings=True,
                                       convert_to_numpy=True)
        emb = emb.astype(np.float32)
        scores, idxs = self._index.search(emb, top_k)
        out: list[tuple[Chunk, float]] = []
        for idx, score in zip(idxs[0], scores[0]):
            if idx < 0 or idx >= len(self._chunks):
                continue
            out.append((self._chunks[idx], float(score)))
        return out
