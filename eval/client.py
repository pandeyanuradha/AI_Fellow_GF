"""
Endpoint client — calls the maternal-health Q&A endpoint over HTTP.

Why a separate client: the evaluator must be agnostic to WHAT it's testing.
Today it tests our own FastAPI app; tomorrow it could test a CeRAI install,
a Vaidya AI WhatsApp bot, or anything else with a POST /chat interface.
"""

from __future__ import annotations

import httpx


class EndpointClient:
    def __init__(self, base_url: str, timeout_s: float = 60.0) -> None:
        # Trailing slash matters; strip it for consistency.
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def ask(self, question: str) -> str:
        """POST a question, return the raw response text (possibly empty)."""
        try:
            r = httpx.post(
                f"{self.base_url}/chat",
                json={"message": question},
                timeout=self.timeout_s,
            )
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            # Surface as a TRUE error, not silently as score=0 (contrast CeRAI).
            raise RuntimeError(f"Endpoint call failed: {e}") from e

        # Schema: {"response": "...", "sources": [...]}
        # Empty / missing response → return "" so refusal classifier handles it.
        return (payload.get("response") or "").strip()
