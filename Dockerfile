# Hugging Face Space Dockerfile for the maternal-health Q&A endpoint.
# Deployed as a Docker SDK space; the FastAPI app listens on port 7860
# (HF Spaces standard port).

FROM python:3.11-slim

# --- system deps: needed for FAISS ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python deps ---
COPY requirements.txt /app/requirements.txt
# HF Spaces will use cached layers when only code changes; install deps first.
RUN pip install --no-cache-dir -r requirements.txt

# --- pre-download the embedding model so the first request isn't slow ---
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# --- app code (endpoint only — eval is not deployed) ---
COPY endpoint /app/endpoint
COPY common /app/common
COPY pyproject.toml /app/pyproject.toml

# --- build the FAISS index at image build time ---
# RAG corpus is shipped with the image; reviewers don't need to re-index.
ENV RAG_CORPUS_DIR=endpoint/corpus
ENV RAG_INDEX_DIR=endpoint/index
ENV RAG_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RUN python -m endpoint.build_index

# --- HF Spaces conventions ---
# - listen on 0.0.0.0:7860
# - secret GROQ_API_KEY injected via HF Space Settings → Variables and secrets
ENV PYTHONUNBUFFERED=1
ENV LLM_PROVIDER=groq
ENV TARGET_MODEL=llama-3.3-70b-versatile
EXPOSE 7860

CMD ["uvicorn", "endpoint.app:app", "--host", "0.0.0.0", "--port", "7860"]
