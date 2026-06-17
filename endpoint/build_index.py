"""
Build the FAISS index from the corpus directory.

Run once after dropping new PDFs / texts into endpoint/corpus/:

    python -m endpoint.build_index
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .rag import RagIndex, load_chunks


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    corpus_dir = Path(os.environ.get("RAG_CORPUS_DIR", "endpoint/corpus"))
    index_dir = Path(os.environ.get("RAG_INDEX_DIR", "endpoint/index"))
    model = os.environ.get(
        "RAG_EMBEDDING_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )

    if not corpus_dir.exists():
        print(f"ERROR: corpus dir does not exist: {corpus_dir}", file=sys.stderr)
        print("Drop PDFs / .md / .txt files into that directory first.", file=sys.stderr)
        return 1

    chunks = load_chunks(corpus_dir)
    if not chunks:
        print(f"ERROR: no chunks extracted from {corpus_dir} — nothing to index.",
              file=sys.stderr)
        return 1

    idx = RagIndex(embedding_model=model, index_dir=index_dir)
    idx.build(chunks)
    idx.save()
    print(f"OK: indexed {len(chunks)} chunks → {index_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
