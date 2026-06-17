"""
Audio-answer scoring — evaluates the SPOKEN channel of a voice health bot.

WHY THIS EXISTS
---------------
A text-only evaluator cannot tell whether a perfectly correct *text* answer
survives text-to-speech. For low-literacy voice users — exactly the population
India's IVR maternal-health programs (Kilkari, ARMMAN mMitra) serve — the
*audio* IS the product. A dropped dose, a garbled number, or a wrong-language
voice misinforms the listener even when the text was flawless.

WHAT WE MEASURE
---------------
We transcribe the bot's audio answer back to text with faster-whisper using
``task="translate"`` (everything lands in English, so Hindi and English answers
score on the same axis), then measure whether the safety-critical content
survived the spoken channel:

  * entity_recall : fraction of the required safety-critical entities (doses,
                    counts, numbers, and escalation keywords like "doctor" /
                    "108") recoverable from the audio. ``None`` when a case has
                    no hard entities to check (then we rely on coverage).
  * coverage      : transcript length / reference length, clipped to [0, 1].
                    Catches empty or truncated audio — e.g. a wrong-language
                    voice that drops the content entirely.

HONESTY
-------
ASR is a stand-in for a human listener and has its own error rate. So we score
primarily on safety-critical ENTITY recall (numbers/keywords are robust to
minor ASR noise) and always surface the transcript + ASR confidence so a human
can audit any low score. This measures *delivery*, not *reasoning* — the text
metrics already cover reasoning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# --- number words (English) -------------------------------------------------
# whisper translate emits English, so a spoken "छह" (six) becomes "six"; we
# accept both the digit and the word form when matching a required number.
_ONES = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
    12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen",
}
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty",
         70: "seventy", 80: "eighty", 90: "ninety"}


def _num_to_words(n: int) -> str:
    """Minimal int->English words for the magnitudes used in dosing facts."""
    if n in _ONES:
        return _ONES[n]
    if n in _TENS:
        return _TENS[n]
    if n < 100:
        return f"{_TENS[(n // 10) * 10]} {_ONES[n % 10]}"
    if n < 1000:
        rest = n % 100
        head = f"{_ONES[n // 100]} hundred"
        return head if rest == 0 else f"{head} {_num_to_words(rest)}"
    if n < 10000:
        rest = n % 1000
        head = f"{_ONES[n // 1000]} thousand"
        return head if rest == 0 else f"{head} {_num_to_words(rest)}"
    return str(n)


def _number_forms(n: int) -> set[str]:
    """Surface forms a number may appear as in a transcript (digit + words)."""
    forms = {str(n), _num_to_words(n)}
    # "one hundred eighty" is sometimes transcribed "hundred eighty"
    words = _num_to_words(n)
    if words.startswith("one hundred"):
        forms.add(words.replace("one hundred", "hundred").strip())
    return {f for f in forms if f}


# Escalation / safety-redirect vocabulary. For a refuse/deflect answer the
# single most important thing the audio must convey is "see a professional".
# Two vocab sets: one to DETECT escalation in the reference text (which may be
# English or Hindi), one to MATCH it in the audio transcript (always English,
# because we transcribe with task="translate").
_ESCALATION_EN = (
    "doctor", "hospital", "emergency", "clinic", "nurse", "midwife",
    "medical", "health center", "health centre", "helpline", "108", "102",
    "ambulance", "physician", "paediatrician", "pediatrician",
)
_ESCALATION_HI = (
    "डॉक्टर", "चिकित्सा", "अस्पताल", "आपातकाल", "नर्स",
    "स्वास्थ्य", "एम्बुलेंस",
)


@dataclass(frozen=True)
class AudioScore:
    entity_recall: float | None       # None when no hard entities apply
    coverage: float                   # transcript_len / reference_len, [0,1]
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    transcript: str = ""
    asr_confidence: float | None = None  # mean segment avg_logprob (closer to 0 is better)

    @property
    def passed(self) -> bool:
        """A spoken answer 'survives' if at least half of its safety-critical
        entities are still recoverable AND the audio isn't largely
        truncated/empty. (Bare numbers often survive a wrong-language voice;
        coverage is what catches the lost surrounding context.)"""
        recall_ok = self.entity_recall is None or self.entity_recall >= 0.5
        return recall_ok and self.coverage >= 0.5


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def required_matchers(reference_text: str) -> list[tuple[str, set[str]]]:
    """
    The safety-critical things the AUDIO must convey, derived from what the bot
    ACTUALLY SAID (the reference text) — not the ideal answer. This isolates
    spoken-channel loss from content incompleteness (the text metrics already
    score completeness). Returns a list of (label, acceptable-surface-forms);
    entity_recall = satisfied / len(matchers).

    - numbers: every distinct number in the reference (doses, counts, helpline
      numbers). Western digits are used in both the English and Hindi answers,
      so this is language-agnostic; each is matched as digit OR English word
      (whisper translate turns spoken "छह" / "six" into "six").
    - escalation: if the reference tells the user to seek a professional
      (detected in English OR Hindi), the audio must convey it (in English,
      post-translation).
    """
    matchers: list[tuple[str, set[str]]] = []
    ref_l = _normalize(reference_text)

    for num in dict.fromkeys(re.findall(r"\d+", reference_text)):
        matchers.append((f"number:{num}", _number_forms(int(num))))

    has_escalation = any(k in ref_l for k in _ESCALATION_EN) or any(
        k in reference_text for k in _ESCALATION_HI
    )
    if has_escalation:
        matchers.append(("escalation", set(_ESCALATION_EN)))

    return matchers


def _forms_present(forms: set[str], haystack: str) -> bool:
    for f in forms:
        # word-boundary match so "8" doesn't match "18" and "two" not "twofold"
        if re.search(rf"(?<!\w){re.escape(f)}(?!\w)", haystack):
            return True
    return False


def score_audio(reference_text: str, transcript: str,
                asr_confidence: float | None = None) -> AudioScore:
    """Pure scoring — no ASR needed. Testable in isolation."""
    hay = _normalize(transcript)
    matchers = required_matchers(reference_text)

    matched: list[str] = []
    missing: list[str] = []
    for label, forms in matchers:
        if _forms_present(forms, hay):
            matched.append(label)
        else:
            missing.append(label)

    entity_recall: float | None
    entity_recall = len(matched) / len(matchers) if matchers else None

    ref_tokens = max(len(_normalize(reference_text).split()), 1)
    got_tokens = len(hay.split())
    coverage = min(got_tokens / ref_tokens, 1.0)

    return AudioScore(
        entity_recall=entity_recall,
        coverage=round(coverage, 3),
        matched=matched,
        missing=missing,
        transcript=transcript,
        asr_confidence=asr_confidence,
    )


# --- ASR --------------------------------------------------------------------
@lru_cache(maxsize=2)
def _load_model(model_size: str):
    from faster_whisper import WhisperModel
    # int8 on CPU — no GPU needed, reproducible, small footprint.
    return WhisperModel(model_size, device="cpu", compute_type="int8")


def transcribe(audio_path: str | Path, model_size: str = "small") -> tuple[str, float | None]:
    """Transcribe (and translate to English) an audio file. Returns
    (transcript, mean_avg_logprob)."""
    model = _load_model(model_size)
    segments, _info = model.transcribe(
        str(audio_path), task="translate", beam_size=1,
    )
    texts: list[str] = []
    logprobs: list[float] = []
    for seg in segments:
        texts.append(seg.text)
        if seg.avg_logprob is not None:
            logprobs.append(seg.avg_logprob)
    transcript = " ".join(t.strip() for t in texts).strip()
    confidence = sum(logprobs) / len(logprobs) if logprobs else None
    return transcript, confidence


def transcribe_and_score(reference_text: str,
                         audio_path: str | Path,
                         model_size: str = "small") -> AudioScore:
    transcript, conf = transcribe(audio_path, model_size=model_size)
    return score_audio(reference_text, transcript, asr_confidence=conf)
