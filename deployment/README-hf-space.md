---
title: Maternal Health Q&A
emoji: 👶
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: India maternal & child health Q&A — eval-tool assignment
---

# Maternal & Child Health Q&A

A small India-focused maternal and child health Q&A endpoint built as the live evaluation target for a CeRAI evaluation-tool assignment.

**Stack:**
- FastAPI
- Groq `llama-3.3-70b-versatile` for generation
- FAISS RAG over WHO / UNICEF / MoHFW maternal-health documents
- Python-side safety pre-filter for hard-refuse and clinical-deflect cases (no external safety service required)

**Endpoints:**
- `POST /chat` — body `{"message": "..."}` → `{"response": "...", "sources": [...], "safety_action": "..."}`
- `GET /docs` — interactive Swagger UI
- `GET /health` — liveness probe

**Why this exists:** It pairs with a reference evaluator (in the GitHub source repo) that demonstrates correct refusal handling, multilingual bias detection, and self-bias-free factuality — all three of which are observably broken in the upstream CeRAI AIEvaluationTool. See the findings document linked from the source repo.

**Configuration secrets:** set `GROQ_API_KEY` in the Space settings.
