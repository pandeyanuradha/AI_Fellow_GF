"""
Main evaluation runner — loads cases, calls endpoint, applies metrics,
emits JSON results + HTML report.

Run with:
    python -m eval.runner --endpoint http://localhost:8000

Or against a deployed endpoint:
    python -m eval.runner --endpoint https://myname-maternal-health-qa.hf.space
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from .cases import TestCase, load_cases
from .client import EndpointClient
from .metrics.bias import BiasScore, score_bias
from .metrics.factuality import FactualityJudge, FactualityScore
from .metrics.refusal import classify_refusal
from .metrics.safety_aware import SafetyAwareScore, score_safety_aware

logger = logging.getLogger(__name__)


# ---- per-category metric application ---------------------------------------


def _serialize(obj: object) -> object:
    """Make dataclasses + Pydantic models JSON-friendly."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dataclass_fields__"):
        d = asdict(obj)
        # Normalise enums
        for k, v in list(d.items()):
            if hasattr(v, "value"):
                d[k] = v.value
        return d
    return obj


def evaluate_case(
    case: TestCase,
    response_text: str,
    factuality_judge: FactualityJudge | None,
    bias_model: str,
) -> dict:
    """
    Apply the right metrics for this case's category. Returns a dict.

    Every case gets ``safety_aware`` (because every case has an
    expected_behaviour). Additional metrics layer on top by category.
    """
    metrics: dict[str, object] = {}

    # Safety-aware is universal.
    safety = score_safety_aware(response_text, case.expected_behaviour)
    metrics["safety_aware"] = safety

    # Factuality applies when the case has expected_facts.
    if case.expected_facts and factuality_judge is not None:
        fact: FactualityScore = factuality_judge.score(
            case.question, response_text, case.expected_facts
        )
        metrics["factuality"] = fact

    # Bias metric applies to the bias category, and as a check on any
    # case that produced a non-refusal answer (we want to detect bias in
    # otherwise-correct factual answers too).
    refusal = classify_refusal(response_text)
    if case.category == "bias" or (not refusal.is_refusal):
        bias: BiasScore = score_bias(response_text, model_name=bias_model)
        metrics["bias"] = bias

    # Build a single "passed" flag for headline reporting.
    # A case passes if safety_aware passed AND (no factuality OR factuality > 0.5)
    # AND (no bias OR bias label != "biased").
    passed = bool(safety.passed)
    if "factuality" in metrics:
        passed = passed and metrics["factuality"].score >= 0.5  # type: ignore[attr-defined]
    if "bias" in metrics:
        bias_obj: BiasScore = metrics["bias"]  # type: ignore[assignment]
        if bias_obj.label == "biased":
            passed = False

    return {
        "case": case.model_dump(),
        "response": response_text,
        "metrics": {k: _serialize(v) for k, v in metrics.items()},
        "passed": passed,
    }


# ---- orchestration ---------------------------------------------------------


def run(
    endpoint_url: str,
    cases_path: Path,
    out_dir: Path,
    target_model: str,
    judge_model: str,
    bias_model: str,
    provider: str | None = None,
) -> dict:
    """Run the evaluator end-to-end. Returns the summary dict."""
    cases = load_cases(cases_path)
    logger.info("Loaded %d cases from %s", len(cases), cases_path)

    client = EndpointClient(endpoint_url)

    factuality_judge: FactualityJudge | None
    try:
        factuality_judge = FactualityJudge(
            target_model=target_model,
            judge_model=judge_model,
            provider=provider,
        )
    except ValueError as e:
        # Misconfig (e.g. target == judge) → still run safety_aware + bias
        # (no LLM needed). Better partial results than CeRAI-style silent zeros.
        logger.warning("Factuality judge disabled: %s", e)
        factuality_judge = None

    results: list[dict] = []
    started_at = time.time()
    for i, case in enumerate(cases, 1):
        logger.info("[%d/%d] %s (%s)", i, len(cases), case.id, case.category)
        try:
            response = client.ask(case.question)
        except RuntimeError as e:
            # Real endpoint error — record as such, do NOT score as 0.
            # (Contrast CeRAI's is_error_response → silent test failure.)
            results.append({
                "case": case.model_dump(),
                "response": None,
                "error": str(e),
                "metrics": {},
                "passed": False,
            })
            continue

        result = evaluate_case(case, response, factuality_judge, bias_model)
        results.append(result)

    duration_s = time.time() - started_at

    # Headline summary
    by_category: dict[str, dict[str, int]] = {}
    for r in results:
        cat = r["case"]["category"]
        by_category.setdefault(cat, {"total": 0, "passed": 0})
        by_category[cat]["total"] += 1
        if r["passed"]:
            by_category[cat]["passed"] += 1

    summary = {
        "endpoint": endpoint_url,
        "target_model": target_model,
        "judge_model": judge_model,
        "bias_model": bias_model,
        "factuality_judge_enabled": factuality_judge is not None,
        "total_cases": len(cases),
        "passed_total": sum(1 for r in results if r["passed"]),
        "by_category": by_category,
        "duration_seconds": round(duration_s, 1),
        "results": results,
    }

    # Persist.
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "results.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %s", json_path)

    # Lazy-import to avoid jinja2 cost on imports.
    from .report import render_html_report
    html_path = out_dir / "report.html"
    render_html_report(summary, html_path)
    logger.info("Wrote %s", html_path)

    return summary


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    p = argparse.ArgumentParser(description="Reference evaluator for maternal-health Q&A.")
    p.add_argument(
        "--endpoint",
        default=os.environ.get("ENDPOINT_URL", "http://localhost:8000"),
        help="Base URL of the endpoint to evaluate.",
    )
    p.add_argument("--cases", default="eval/cases.yaml", type=Path)
    p.add_argument("--out", default="docs/results", type=Path,
                   help="Output directory for results.json + report.html.")
    args = p.parse_args(argv)

    target_model = os.environ.get("TARGET_MODEL", "qwen2.5:7b")
    judge_model = os.environ.get("JUDGE_MODEL", "llama3.2:3b")
    bias_model = os.environ.get(
        "BIAS_MODEL", "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
    )
    provider = os.environ.get("LLM_PROVIDER", "ollama")

    summary = run(
        endpoint_url=args.endpoint,
        cases_path=args.cases,
        out_dir=args.out,
        target_model=target_model,
        judge_model=judge_model,
        bias_model=bias_model,
        provider=provider,
    )

    # Console summary
    print()
    print("=" * 60)
    print(f"  Passed: {summary['passed_total']} / {summary['total_cases']}")
    for cat, stats in summary["by_category"].items():
        print(f"    {cat:<20} {stats['passed']:>3} / {stats['total']}")
    print(f"  Duration: {summary['duration_seconds']}s")
    print(f"  Report:   {args.out / 'report.html'}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
