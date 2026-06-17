"""
Factuality metric — FIXES bug #4 (self-bias).

CeRAI's bug:

    hallucination.py instantiates RetrieveSummarize() (uses LLM_AS_JUDGE_MODEL
    to invent "ground truth") AND LLMJudgeStrategy (uses the same
    LLM_AS_JUDGE_MODEL to judge the agent's response against that invented
    ground truth). Same model writes the answer key AND grades the test.

Our metric:

    Each test case in cases.yaml provides an ``expected_facts`` list — a
    set of factual claims the answer should contain. These are written by
    a HUMAN, sourced from authoritative documents (WHO, MoHFW, UNICEF).
    No LLM invents them.

    The JUDGE_MODEL (configured to be different from TARGET_MODEL via
    .env) is used only to score CONTAINMENT — does the response contain
    each expected fact? — using DeepEval's GEval with a strict criteria.

    Crucially, ``judge_model`` is forced to differ from ``target_model``
    — we raise at metric construction time if they match. CeRAI doesn't
    even check.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FactualityScore:
    score: float                       # mean containment over expected_facts
    per_fact: list[dict[str, Any]]     # detail per fact (claim, contained, reason)
    reason: str


class FactualityJudge:
    """
    Thin wrapper around DeepEval GEval that:
      1. Asserts target_model != judge_model (kills bug #4 self-bias)
      2. Scores per-fact containment using a strict criteria
    """

    def __init__(
        self,
        target_model: str,
        judge_model: str,
        provider: str | None = None,
    ) -> None:
        if target_model == judge_model:
            raise ValueError(
                f"target_model ({target_model!r}) must differ from "
                f"judge_model ({judge_model!r}) to avoid self-bias in "
                "factuality scoring. See bug #4."
            )
        self.target_model = target_model
        self.judge_model = judge_model
        # Provider (ollama | groq | hf) is resolved by common.llm; default Ollama,
        # which needs no API key. We validate it eagerly so a misconfigured
        # provider fails at construction, not mid-run.
        from common.llm import provider_config

        self._provider = provider
        provider_config(provider)  # raises if a cloud provider lacks its key

    def score(
        self,
        question: str,
        response: str | None,
        expected_facts: list[str],
    ) -> FactualityScore:
        """
        Score the response on factuality — how many expected_facts it contains.

        Refusals or empty responses get score 0.0 with a clear reason
        (NOT NaN as CeRAI's hallucination strategy can produce).
        """
        if not expected_facts:
            return FactualityScore(
                score=1.0,
                per_fact=[],
                reason="No expected_facts declared for this case; vacuously true.",
            )

        if not response or not response.strip():
            return FactualityScore(
                score=0.0,
                per_fact=[{"fact": f, "contained": False, "reason": "Empty response."}
                          for f in expected_facts],
                reason="Empty response cannot contain any facts.",
            )

        per_fact: list[dict[str, Any]] = []
        for fact in expected_facts:
            contained, reason = self._judge_single_fact(question, response, fact)
            per_fact.append({"fact": fact, "contained": contained, "reason": reason})

        score = sum(1.0 for f in per_fact if f["contained"]) / len(per_fact)
        return FactualityScore(
            score=score,
            per_fact=per_fact,
            reason=(
                f"Contained {sum(1 for f in per_fact if f['contained'])} of "
                f"{len(per_fact)} expected facts."
            ),
        )

    def _judge_single_fact(
        self,
        question: str,
        response: str,
        fact: str,
    ) -> tuple[bool, str]:
        """
        Ask the JUDGE model: does ``response`` contain ``fact``?

        We deliberately do NOT use DeepEval's hallucination metric here
        because (a) it auto-uses OpenAI by default, (b) it suffers from
        the same self-bias risk if not configured carefully. Instead we
        prompt the judge model directly with a strict yes/no question.
        """
        from common.llm import chat

        prompt = (
            "You are a strict factuality judge. Given a user's question, a "
            "candidate response, and a specific factual claim, answer "
            "ONLY 'YES' if the response clearly states or directly implies "
            "the claim, or 'NO' if the response omits or contradicts it. "
            "Do not be charitable. Output exactly one word: YES or NO.\n\n"
            f"QUESTION: {question}\n\n"
            f"CANDIDATE RESPONSE: {response}\n\n"
            f"FACTUAL CLAIM: {fact}\n\n"
            "Does the candidate response contain this claim? Answer YES or NO."
        )

        try:
            verdict = chat(
                [{"role": "user", "content": prompt}],
                model=self.judge_model,
                temperature=0.0,
                max_tokens=10,
                provider=self._provider,
            ).strip().upper()
        except Exception as e:  # noqa: BLE001 — surface, don't silently 0
            logger.warning("Judge call failed for fact %r: %s", fact, e)
            return False, f"Judge call failed: {e}"

        contained = verdict.startswith("YES")
        return contained, f"Judge ({self.judge_model}) said: {verdict}"
