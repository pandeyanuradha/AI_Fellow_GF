"""
Provider-configurable LLM client (OpenAI-compatible).

One small surface — ``chat(messages, model, ...)`` — that talks to any
OpenAI-compatible chat-completions API. The provider is selected by the
``LLM_PROVIDER`` environment variable:

  ollama  (default)   local Ollama, ZERO API keys, fully reproducible
  groq                Groq free tier
  hf                  Hugging Face Inference router (for the deployed Space)

Why this seam exists
--------------------
The SAME endpoint and judge code must run in two places:

  1. Locally on Ollama for the reproducible results run (no keys, no cloud).
  2. On a hosted Hugging Face Space when deployed — which CANNOT reach a
     developer's local Ollama, so it needs a cloud provider.

Routing both through one OpenAI-compatible client means we change a single
env var (``LLM_PROVIDER``) instead of forking the code. Ollama, Groq, and the
HF Inference router all speak the same ``/chat/completions`` dialect.

We deliberately fail LOUD on a misconfigured provider (raise), rather than
returning an empty string — the opposite of CeRAI's safety.py, which swallows
a missing GPU_URL and silently yields empty output.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str


def provider_config(provider: str | None = None) -> ProviderConfig:
    """Resolve the OpenAI-compatible base_url + api_key for the active provider."""
    provider = (provider or os.environ.get("LLM_PROVIDER", "ollama")).lower()

    if provider == "ollama":
        return ProviderConfig(
            name="ollama",
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            # Ollama ignores the key, but the OpenAI SDK requires a non-empty string.
            api_key=os.environ.get("OLLAMA_API_KEY", "ollama"),
        )

    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            raise RuntimeError(
                "LLM_PROVIDER=groq but GROQ_API_KEY is not set. "
                "Copy .env.example to .env and fill it in."
            )
        return ProviderConfig(
            name="groq",
            base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            api_key=key,
        )

    if provider == "hf":
        key = os.environ.get("HF_TOKEN", "")
        if not key:
            raise RuntimeError(
                "LLM_PROVIDER=hf but HF_TOKEN is not set. "
                "Set a read-scope token: https://huggingface.co/settings/tokens"
            )
        return ProviderConfig(
            name="hf",
            base_url=os.environ.get("HF_BASE_URL", "https://router.huggingface.co/v1"),
            api_key=key,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER={provider!r}; expected one of: ollama | groq | hf."
    )


def chat(
    messages: list[dict[str, str]],
    model: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 400,
    provider: str | None = None,
) -> str:
    """Run a chat completion and return the assistant text (stripped)."""
    from openai import OpenAI

    cfg = provider_config(provider)
    client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()
