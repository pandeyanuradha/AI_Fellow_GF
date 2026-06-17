"""
Test-case schema and loader. Cases live in ``eval/cases.yaml``.

DESIGN: a case is a self-contained spec. NO defaulting to "auto" strategies
(bug #1). NO inferring expected behaviour from the prompt. Every
case explicitly declares what's expected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


Category = Literal[
    "factuality",
    "safety_refuse",
    "safety_deflect",
    "safety_answer",
    "bias",
    "multilingual",
]


class TestCase(BaseModel):
    id: str = Field(..., description="Stable unique ID, e.g. 'fact_001'")
    category: Category
    language: Literal["en", "hi"] = "en"
    question: str
    expected_behaviour: Literal["answer", "refuse", "deflect"]
    expected_facts: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, description="Author notes; not scored.")

    @field_validator("expected_facts")
    @classmethod
    def _validate_facts(cls, v: list[str], info) -> list[str]:
        # Factuality cases must declare at least one fact; safety cases shouldn't.
        category = info.data.get("category")
        expected = info.data.get("expected_behaviour")
        if category == "factuality" and not v:
            raise ValueError(
                f"factuality cases must declare expected_facts (case {info.data.get('id')!r})"
            )
        if expected != "answer" and v:
            raise ValueError(
                f"cases with expected_behaviour={expected!r} must not declare "
                f"expected_facts (case {info.data.get('id')!r})"
            )
        return v


def load_cases(path: str | Path) -> list[TestCase]:
    """Load and validate test cases from a YAML file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a YAML list at the top level")
    cases = [TestCase.model_validate(item) for item in raw]
    seen: set[str] = set()
    for c in cases:
        if c.id in seen:
            raise ValueError(f"Duplicate case id: {c.id!r}")
        seen.add(c.id)
    return cases
