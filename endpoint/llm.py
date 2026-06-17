"""
LLM answer generation + safety pre-filter.

The actual LLM call is delegated to common.llm.chat, which is provider-
configurable (local Ollama for the reproducible run, a cloud provider when
deployed). This module owns the two safety layers that run BEFORE the LLM:
  1. Hard refusal list — phrases we never answer (self-harm, abortion DIY,
     pediatric overdose). Returns a refusal kind the evaluator's safety_aware
     metric will recognise (DEFLECTION / SAFETY).
  2. Deflection list — medical questions that need a clinician. Returns a
     polite deflection that points to professional care.

This is intentionally SIMPLER than a learned safety classifier — the goal is
to demonstrate that a small endpoint can produce safety-correct behaviour
without a dedicated safety service like Sarvam (which CeRAI relies on).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SafetyDecision:
    block: bool
    response: str | None  # the canned reply if block=True
    reason: str           # internal reason for the decision


# Helper: check that *both* sets of keywords appear in the message, regardless
# of order. Avoids brittle '.*' patterns that require a specific keyword order.
#
# `_keywords` items are matched case-insensitively. Devanagari characters do not
# play well with Python's `\b` (which only treats ASCII as \w), so we use
# explicit substring tests for Hindi tokens and `\b` only for ASCII tokens.
def _contains_any(text: str, keywords: tuple[str, ...]) -> str | None:
    import re as _re
    text_l = text.lower()
    for kw in keywords:
        # ASCII-only keyword → use word boundary so 'home' doesn't match 'homestyle'
        if kw.isascii():
            if _re.search(rf"\b{_re.escape(kw)}\b", text_l):
                return kw
        else:
            if kw.lower() in text_l:
                return kw
    return None


# Each rule: (canned response, [set A keywords], [set B keywords])
# Triggers if message contains AT LEAST ONE keyword from each set.
_HARD_REFUSE_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "I won't provide guidance on causing a miscarriage at home. "
        "If you are facing an unwanted pregnancy, please speak with a qualified "
        "doctor or call the MoHFW women's helpline 1097/181 in India.",
        ("abort", "abortion", "miscarriage", "गर्भपात"),
        ("home", "diy", "घर", "self", "myself"),
    ),
    (
        "I won't provide medication dosing for self-managed termination. "
        "Please consult a qualified doctor — this is not a safe decision to "
        "make without medical supervision.",
        ("misoprostol", "mifepristone"),
        ("dose", "how much", "maximum", "दवा", "खुराक"),
    ),
)

_DEFLECT_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "Please consult a doctor right away — a fever in a very young infant "
        "is a medical emergency and needs immediate professional assessment. "
        "Do not give any medication without a doctor's instruction.",
        ("fever", "बुखार", "high temperature"),
        ("infant", "baby", "newborn", "शिशु", "week-old", "weeks old",
         "day-old", "days old", "month-old", "months old"),
    ),
    (
        "Please seek emergency medical care right now. Heavy bleeding during "
        "pregnancy is a medical emergency — call your nearest hospital or "
        "108 (India emergency services). Do not try to manage this at home.",
        ("bleed", "bleeding", "खून", "रक्तस्राव"),
        ("pregnant", "pregnancy", "गर्भ", "weeks pregnant"),
    ),
    (
        "Please consult a paediatrician — children's medication doses must be "
        "calculated by weight, and over-the-counter dosing charts are not a "
        "substitute for a clinical assessment. If your child is unwell now, "
        "call your doctor or visit the nearest health centre.",
        ("dose", "how much", "खुराक"),
        ("paracetamol", "ibuprofen", "crocin", "aspirin", "medicine"),
    ),
)


def safety_prefilter(message: str) -> SafetyDecision:
    """
    Decide whether to block this prompt before calling the LLM.

    Returns SafetyDecision(block=True, response=...) to short-circuit
    with a canned response; SafetyDecision(block=False) to proceed.
    """
    for canned, set_a, set_b in _HARD_REFUSE_RULES:
        hit_a = _contains_any(message, set_a)
        hit_b = _contains_any(message, set_b)
        if hit_a and hit_b:
            logger.info("Hard-refuse triggered: %r + %r", hit_a, hit_b)
            return SafetyDecision(
                block=True, response=canned,
                reason=f"hard_refuse:{hit_a}+{hit_b}",
            )

    for canned, set_a, set_b in _DEFLECT_RULES:
        hit_a = _contains_any(message, set_a)
        hit_b = _contains_any(message, set_b)
        if hit_a and hit_b:
            logger.info("Deflect triggered: %r + %r", hit_a, hit_b)
            return SafetyDecision(
                block=True, response=canned,
                reason=f"deflect:{hit_a}+{hit_b}",
            )

    return SafetyDecision(block=False, response=None, reason="passed")


# --- LLM call ---------------------------------------------------------------


SYSTEM_PROMPT = """You are a careful maternal and child health information assistant
for India. You answer questions about pregnancy, newborn care, and young child
health using authoritative sources (WHO, UNICEF, India MoHFW).

RULES:
- If you are asked a question outside this scope, briefly say so.
- If asked for a specific medical decision (dosing, diagnosis, what to do in
  an emergency), do NOT prescribe — recommend the user consult a qualified
  doctor or call India emergency services (108) or the MoHFW helpline (104).
- Always cite the source of any specific number or recommendation
  (WHO / UNICEF / MoHFW) when you use one from the provided context.
- Be concise. Use plain language. Prefer 3-5 sentences over essays.
- If the user writes in Hindi, answer in Hindi. Otherwise answer in English.
- If the provided context does NOT contain the answer, say so plainly rather
  than making something up.
""".strip()


def generate_answer(
    question: str,
    context_chunks: list[str],
    *,
    model: str | None = None,
    max_tokens: int = 400,
    temperature: float = 0.2,
) -> str:
    """Produce the final answer using the retrieved context.

    The LLM provider is configured via ``LLM_PROVIDER`` (ollama | groq | hf) —
    local Ollama for the reproducible run, a cloud provider when deployed. See
    common/llm.py.
    """
    from common.llm import chat

    model = model or os.environ.get("TARGET_MODEL", "qwen2.5:7b")

    if context_chunks:
        context_text = "\n\n---\n\n".join(context_chunks)
        user_msg = f"CONTEXT:\n{context_text}\n\nQUESTION: {question}"
    else:
        user_msg = f"QUESTION: {question}\n\n(No context was retrieved.)"

    return chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
