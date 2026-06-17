# Bug #3 — `is_error_response()` in TCE backend treats empty text as a connection error

I discovered that correct empty-content refusals are dropped before any strategy can score them, and traced the root cause to the TCE backend.

## The smoking gun

[`src/app/TestCaseExecutorDashboard/back-end/tasks/test_run_tasks.py:19-26`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/TestCaseExecutorDashboard/back-end/tasks/test_run_tasks.py#L19-L26)

```python
def is_error_response(response_text: str) -> bool:
    error_indicators = [
        "chat not found",
        "[error: max retries exceeded]",
        "[error: connection refused]",
        "no response received",
    ]
    text = (response_text or "").lower()
    return (not text.strip()) or any(ind in text for ind in error_indicators)
```

The `(not text.strip())` clause means **any empty / whitespace-only response is classified as a connection error before any strategy runs**.

This is exactly what fails for safety prompts: a well-aligned model (Llama Guard, OpenAI moderation, etc.) returns empty content as its standard refusal. The TCE marks the test as failed with `error`, never giving any strategy a chance to score it as a legitimate refusal.

## Inconsistency that makes it worse

Some strategies DO handle refusals correctly — they just never get the chance because `is_error_response` short-circuits first:

- [`src/lib/strategy/truth_external.py:31-48`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/lib/strategy/truth_external.py#L31-L48) has its own `is_refusal()` with 9 markers, returns `(None, "REFUSED")` for refusals — good behaviour.
- [`src/lib/strategy/efficacy_of_content_filtering.py:40-47`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/lib/strategy/efficacy_of_content_filtering.py#L40-L47) scores refusal as 1 (correct safety behaviour).
- [`src/lib/strategy/privacy.py:147`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/lib/strategy/privacy.py#L147) reduces privacy risk by 65 % for refusals.

But these three use **independent marker lists** that don't agree with each other. There's no single source of truth.

## Suggested fix

**1. Introduce a third test-case state.** Right now there are effectively `COMPLETED` and `ERROR`. Add `REFUSED`. Then `is_error_response` becomes `classify_response → {ANSWERED, REFUSED, ERROR}`.

**2. Centralise refusal detection.** Move all the marker lists from `truth_external.py`, `efficacy_of_content_filtering.py`, `privacy.py` into one module (`src/lib/strategy/_refusal.py`?) that everyone imports. One list, one source of truth.

**3. Per-strategy refusal handling.** Each strategy decides how to score `REFUSED`:
- `safety_*`: refusal → 1.0 (correct behaviour)
- `truth_*`: refusal → `None` (skip)
- `bias_*`: refusal → `None` (skip — can't measure bias in a refusal)
- etc.

## Reference implementation

We built a small refusal classifier in Python that does exactly this — a single `classify_refusal(text) -> {empty, policy, scope, safety, deflection, not_refusal}` function used by every metric. Happy to share the design / code if useful.

Confirmed against commit `<SHA>` of `main`.
