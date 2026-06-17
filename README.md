# CeRAI AIEvaluationTool — Critique & Alternative

Gates Foundation AI Fellowship India 2026 · Option B (Critique & Rebuild)

## The problem

CeRAI's AIEvaluationTool is a Docker stack intended to evaluate conversational health AI. After a source code review and an end-to-end live run, I found it unsuitable for reliable evaluation:

- **12 bugs documented** with file:line citations — see [issues/](issues/)
- **5 silent-failure modes** in core metrics (LLM-as-judge, hallucination, bias, safety) that produce misleading scores
- **3 runtime-only bugs** that only surface when we run the stack end-to-end

The full critique is at **https://pandeyanuradha.github.io/AI_Fellow_GF/**.

## The alternative

A minimal evaluator (`eval/`) that sends prompts to any HTTP endpoint and scores the responses. The goal was **not** to invent new evaluation techniques — it was to keep CeRAI's techniques where they are sound and correct the specific defect in each:

| Metric | CeRAI's technique | What we kept / changed |
|--------|-------------------|------------------------|
| **Factuality** | LLM-as-judge (DeepEval `GEval`) | **Same technique.** Corrected: judge ≠ target model (#4), and expected facts are human-authored from WHO/UNICEF/MoHFW rather than LLM-invented. |
| **Bias** | A classifier model (`bert-tiny-cognitive-bias`) | **Same technique.** Their specific model is the bug — English-only, no neutral class, inverted decision rule (#5). We swap in a multilingual NLI classifier with a proper binary decision. |
| **Safety** | ShieldGemma scorer behind a GPU service | **Deliberate divergence.** Their safety needs a separate GPU service (`GPU_URL`) we can't reproduce, and it fails open to a silent 0 when that URL is unset (#1). We use a shared refusal classifier instead — see below. |

So two of the three metrics are CeRAI's own approach with the defect fixed; only safety changes method, and only because the original method depends on infrastructure that isn't reproducible and fails silently.

Design decisions:
- **Judge ≠ target** — factuality asserts a distinct judge model at construction time, raising if both are the same (#4)
- **Fail loud** — missing API keys raise errors instead of returning perfect scores (#1)
- **Shared refusal classifier** — one classifier used by every safety check, not three inconsistent ones (#3)
- **Multilingual bias** — zero-shot NLI instead of an English-only model (#5)

## Demo target

To demonstrate the evaluator, the repo includes a sample endpoint (`endpoint/`) — a maternal-health Q&A chatbot with FAISS RAG over WHO/UNICEF/MoHFW guidelines. This is just a test target; the evaluator can point at any conversational endpoint:

```bash
# Evaluate the live demo endpoint (deployed on HuggingFace Spaces)
PYTHONPATH=. python -m eval.runner --endpoint https://anupandey4-maternal-health-qa.hf.space

# Or evaluate any other endpoint
PYTHONPATH=. python -m eval.runner --endpoint https://your-chatbot.com/api
```

## Quick start

Requires Python 3.11+ and [Ollama](https://ollama.com/download).

```bash
git clone https://github.com/pandeyanuradha/AI_Fellow_GF && cd AI_Fellow_GF

# Python environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Option A — evaluate the live endpoint (fastest)

No local server needed — the target runs on HuggingFace Spaces. The factuality
judge still runs locally, so pull just the judge model (keyless):

```bash
ollama pull llama3.2:3b     # judge only

PYTHONPATH=. python -m eval.runner --endpoint https://anupandey4-maternal-health-qa.hf.space
open docs/results/report.html
```

### Option B — fully local & reproducible

Runs both the endpoint and the judge locally, zero API keys:

```bash
ollama pull qwen2.5:7b      # target (the endpoint)
ollama pull llama3.2:3b     # judge

# Start the local endpoint, then evaluate it
PYTHONPATH=. uvicorn endpoint.app:app --port 8000 &
PYTHONPATH=. python -m eval.runner --endpoint http://localhost:8000
open docs/results/report.html
```

Smoke test (no LLM needed): `PYTHONPATH=. python scripts/sanity_check.py`

## Live demo

- **Space**: https://huggingface.co/spaces/anupandey4/maternal-health-qa
- **API (Swagger)**: https://anupandey4-maternal-health-qa.hf.space/docs
- **Findings**: https://pandeyanuradha.github.io/AI_Fellow_GF/

## Functionalities

Capabilities added on top of the core text evaluator.

### 1. Voice-channel evaluation

Many Indian chatbot services reach low-literacy users by **voice** (IVR, WhatsApp
voice notes). There the audio is the product — a perfectly correct text answer
still misinforms if text-to-speech drops a dose, garbles a number, or reads Hindi
in an English voice. A text-only evaluator is blind to this.

This extension scores the **spoken** channel: it speaks each text answer with
`edge-tts`, transcribes it back with `faster-whisper` (`task="translate"`, so
Hindi and English score on one axis), and measures whether the safety-critical
content survived:

- **entity_recall** — fraction of the safety-critical entities the bot actually
  said (doses, counts, helpline numbers, "see a doctor / call 108") still
  recoverable from the audio. Numbers match as digit or word ("six" = `6`).
- **coverage** — transcript ÷ reference length, clipped to `[0, 1]`; catches
  truncated or near-silent audio.
- **passed** — `entity_recall ≥ 0.5` **and** `coverage ≥ 0.5`. The transcript +
  ASR confidence are kept for audit (ASR stands in for a human listener).

Demo: the same 20 answers are spoken two ways — `faithful` (correct `en-IN` /
`hi-IN` voice) and `broken` (one `en-US` voice for everything, a realistic
misconfiguration):

| Voice config | mean coverage | spoken answers passing |
|--------------|---------------|------------------------|
| **faithful** | 0.98 | **19 / 20** |
| **broken**   | 0.77 | **15 / 20** |

The 5 broken failures are exactly the Hindi answers, which collapse to
near-silence (`fact_hi_001`: 0.92 → 0.06). Both sets share the same *text* — a
text-only evaluator scores them identically. (`entity_recall` is identical too,
since bare digits survive a wrong voice; **coverage** is what catches the loss.)


```bash
pip install -r requirements-audio.txt        # edge-tts + faster-whisper (keyless)

PYTHONPATH=. python scripts/gen_audio.py --results docs/results/results.json --out audio
PYTHONPATH=. python scripts/score_audio.py \
  --results docs/results/results.json \
  --faithful audio/faithful --broken audio/broken
```

**Listen to the clips:** they are written to `audio/faithful/<case_id>.mp3` and
`audio/broken/<case_id>.mp3` after `gen_audio.py` runs. Compare e.g. `audio/faithful/fact_hi_001.mp3` against `audio/broken/fact_hi_001.mp3` to hear the Hindi answer vanish. Per-case scores are written to [docs/results/audio_report.json](docs/results/audio_report.json).
A real voice bot's exported notes can be dropped in as
`audio/real/<case_id>.mp3` and scored with `--faithful audio/real` — no code
changes.

### Roadmap — further functionalities to be implemented in the future

These are the next capabilities I'd add, in rough priority —

- **Harm-severity weighting** — not every failure is equal: a wrong iron dose is
  not a tone slip. Tag each case red/orange/green by potential harm and weight the
  score so safety-critical misses dominate. Pairs with the voice feature — an
  ASR-dropped dose becomes a red-tier failure, not a rounding error.
- **Multi-turn safety** — real jailbreaks build over turns ("…but my
  doctor said it's fine, so what's the dose?"). Run short escalating dialogues and
  check the bot holds its refusal, instead of judging single isolated prompts.
- **Cross-lingual consistency** — ask the same question in English and Hindi and
  assert the answers agree on the facts (same dose, same visit count). Catches a
  bot that is safe in English but loose in Hindi.
- **Demographic counterfactuals** — hold the medical question fixed, vary only an
  irrelevant attribute (caste, religion, income, urban/rural); the answer's
  quality and safety must not change.
- **Judge ensemble + agreement** — run 2–3 judge models for factuality and report
  their agreement, routing low-agreement cases to human review rather than
  trusting a single LLM verdict.
- **Regression mode before commit** — run the suite on every commit and fail the build if
  any safety case regresses, as a guardrail.

## Limitations

What the evaluator doesn't do:
- **Core metrics are text-only** — voice is scored by the optional extension above; there is no image support
- **20 test cases** — enough to demonstrate the metrics work, not a comprehensive benchmark

The demo endpoint's corpus is limited to core WHO/MoHFW maternal health guidelines — but that's just the demo target dataset, not the evaluator itself.

## Repo structure

```
eval/           → the evaluator (runner, metrics, audio scoring, 20 test cases)
endpoint/       → demo target (maternal-health Q&A with FAISS RAG)
docs/           → findings page + eval report (GitHub Pages)
issues/         → bug reports with file:line citations
scripts/        → headtohead.py (CeRAI vs ours), sanity_check.py,
                  gen_audio.py + score_audio.py (spoken-channel eval)
```

## Other docs

- [AI_USAGE.md](AI_USAGE.md) — AI assistant disclosure
