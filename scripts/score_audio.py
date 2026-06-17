"""
Offline audio-scoring mode — score a voice bot's spoken answers.

Feed it a results.json (the bot's text answers, used as the reference for what
the audio SHOULD convey) and one or two directories of ``<case_id>.mp3`` audio
answers. It transcribes each clip and reports whether the safety-critical
content survived the spoken channel (see eval/audio.py).

This is endpoint-agnostic: the audio can come from our TTS simulator
(scripts/gen_audio.py) or be real voice-note exports from a WhatsApp/IVR bot —
drop them in a folder named ``<case_id>.mp3`` and point ``--faithful`` at it.

Run (compare the localized voices vs the single-English-voice misconfig):
    python scripts/score_audio.py \
        --results docs/results/results.json \
        --faithful audio/faithful --broken audio/broken
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.audio import transcribe_and_score, AudioScore


def _score_dir(results: dict, audio_dir: Path, model_size: str) -> dict[str, AudioScore]:
    out: dict[str, AudioScore] = {}
    for r in results["results"]:
        cid = r["case"]["id"]
        reference = (r.get("response") or "").strip()
        if not reference:
            continue
        audio = audio_dir / f"{cid}.mp3"
        if not audio.exists():
            continue
        out[cid] = transcribe_and_score(reference, audio, model_size=model_size)
    return out


def _fmt_recall(s: AudioScore | None) -> str:
    if s is None:
        return "    -   "
    r = s.entity_recall
    rs = " n/a " if r is None else f"{r:4.0%}"
    return f"{rs} c={s.coverage:4.2f}"


def _agg(scores: dict[str, AudioScore]) -> dict:
    recalls = [s.entity_recall for s in scores.values() if s.entity_recall is not None]
    covs = [s.coverage for s in scores.values()]
    return {
        "n": len(scores),
        "mean_entity_recall": round(sum(recalls) / len(recalls), 3) if recalls else None,
        "mean_coverage": round(sum(covs) / len(covs), 3) if covs else None,
        "passed": sum(1 for s in scores.values() if s.passed),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", default="docs/results/results.json", type=Path)
    p.add_argument("--faithful", required=True, type=Path,
                   help="Directory of <case_id>.mp3 (primary set to score).")
    p.add_argument("--broken", type=Path, default=None,
                   help="Optional second set to compare against (e.g. a misconfig).")
    p.add_argument("--model", default="small",
                   help="faster-whisper model size (tiny|base|small|medium).")
    p.add_argument("--out", default="docs/results/audio_report.json", type=Path)
    args = p.parse_args(argv)

    results = json.loads(args.results.read_text(encoding="utf-8"))
    by_id = {r["case"]["id"]: r for r in results["results"]}

    print(f"Transcribing with faster-whisper '{args.model}' (translate->English)...\n")
    faithful = _score_dir(results, args.faithful, args.model)
    broken = _score_dir(results, args.broken, args.model) if args.broken else {}

    # Per-case table
    header = f"{'case':18} {'lang':4} | {'faithful':14}"
    if broken:
        header += f" | {'broken':14}"
    print(header)
    print("-" * len(header))
    for cid in faithful:
        lang = by_id[cid]["case"].get("language", "en")
        row = f"{cid:18} {lang:4} | {_fmt_recall(faithful.get(cid)):14}"
        if broken:
            row += f" | {_fmt_recall(broken.get(cid)):14}"
        print(row)

    # Aggregates
    fa = _agg(faithful)
    print("\n=== aggregate ===")
    print(f"faithful: n={fa['n']}  entity_recall={fa['mean_entity_recall']}  "
          f"coverage={fa['mean_coverage']}  passed={fa['passed']}/{fa['n']}")
    report = {"model": args.model, "faithful": fa}
    if broken:
        br = _agg(broken)
        print(f"broken:   n={br['n']}  entity_recall={br['mean_entity_recall']}  "
              f"coverage={br['mean_coverage']}  passed={br['passed']}/{br['n']}")
        report["broken"] = br

    # Per-case detail to JSON
    def _dump(scores: dict[str, AudioScore]) -> dict:
        return {
            cid: {
                "language": by_id[cid]["case"].get("language", "en"),
                "entity_recall": s.entity_recall,
                "coverage": s.coverage,
                "matched": s.matched,
                "missing": s.missing,
                "asr_confidence": s.asr_confidence,
                "transcript": s.transcript,
            }
            for cid, s in scores.items()
        }

    report["faithful_detail"] = _dump(faithful)
    if broken:
        report["broken_detail"] = _dump(broken)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
