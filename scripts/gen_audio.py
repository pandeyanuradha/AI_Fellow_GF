"""
Generate spoken-answer audio for the eval cases — simulating a text->TTS voice
bot (exactly like the WhatsApp bot we're targeting: text answer + identical TTS
audio).

We synthesise each bot text answer under two voice configurations:

  faithful/ : the right Indian voice per language (en-IN, hi-IN) — a correctly
              localized deployment.
  broken/   : a single en-US voice for EVERY language — a common, realistic
              misconfiguration where one English voice is wired up for all
              content. Hindi answers come out mispronounced / dropped, so the
              spoken channel silently loses the information even though the
              underlying TEXT was perfect.

This is the failure a text-only evaluator is blind to. The audio scorer
(`scripts/score_audio.py`) then measures how much survives each rendering.

Input : a results.json produced by `python -m eval.runner` (the bot's text
        answers live in results[].response).
Output: <out>/faithful/<id>.mp3 and <out>/broken/<id>.mp3

Run:
    python scripts/gen_audio.py --results docs/results/results.json --out audio
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

import edge_tts

# Correctly localized voices (Indian English + Hindi neural voices).
FAITHFUL_VOICE = {
    "en": "en-IN-NeerjaNeural",
    "hi": "hi-IN-SwaraNeural",
}
# The misconfiguration: one US English voice used for everything.
BROKEN_VOICE = "en-US-AriaNeural"

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def _detect_lang(text: str) -> str:
    """Pick the faithful voice from the ACTUAL script of the answer, not the
    case label — the endpoint sometimes answers an English prompt in Hindi, and
    a correctly localized bot would voice it with a Hindi voice regardless."""
    return "hi" if _DEVANAGARI.search(text) else "en"


async def _synth(text: str, voice: str, out_path: Path) -> None:
    await edge_tts.Communicate(text, voice).save(str(out_path))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", default="docs/results/results.json", type=Path,
                   help="results.json from the evaluator (source of text answers).")
    p.add_argument("--out", default="audio", type=Path,
                   help="Output dir; creates faithful/ and broken/ subdirs.")
    args = p.parse_args(argv)

    data = json.loads(args.results.read_text(encoding="utf-8"))
    faithful_dir = args.out / "faithful"
    broken_dir = args.out / "broken"
    faithful_dir.mkdir(parents=True, exist_ok=True)
    broken_dir.mkdir(parents=True, exist_ok=True)

    made = 0
    for r in data["results"]:
        cid = r["case"]["id"]
        text = (r.get("response") or "").strip()
        if not text:
            print(f"  skip {cid}: empty response (nothing to speak)")
            continue

        lang = _detect_lang(text)
        faithful_voice = FAITHFUL_VOICE[lang]
        asyncio.run(_synth(text, faithful_voice, faithful_dir / f"{cid}.mp3"))
        asyncio.run(_synth(text, BROKEN_VOICE, broken_dir / f"{cid}.mp3"))
        made += 1
        print(f"  {cid:18} [{lang}]  faithful={faithful_voice:20} broken={BROKEN_VOICE}")

    print(f"\nGenerated audio for {made} cases under {args.out}/ "
          f"(faithful/ + broken/).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
