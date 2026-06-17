# Bug #1 — `strategy="auto"` default + silent-zero in `StrategyImplementor`

I discovered that every test case lacking an explicit `STRATEGY` is scored 0, and traced it to two specific source locations. Documenting them here so the fix is unambiguous.

## Root cause (3 files, 3 lines)

**1. The importer assigns `"auto"` as the default strategy for every test case lacking an explicit `STRATEGY` field:**

[`src/app/importer/main.py:219`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/importer/main.py#L219)
```python
strategy = "auto"
if "STRATEGY" in case:
    ...
```

**2. No `Strategy` subclass anywhere under `src/lib/strategy/` declares `name="auto"`** as its `__init__` default. I grep'd; nothing matches. Therefore `LazyLoader.STRAT_NAME_TO_CLASS_NAME` has no `"auto"` entry, and `StrategyImplementor.find_class_name("auto")` returns `None`.

**3. `StrategyImplementor.execute()` then silently returns `score=0, reason=""`:**

[`src/lib/strategy/strategy_implementor.py:23-40`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/lib/strategy/strategy_implementor.py#L23-L40)
```python
def execute(self, ...):
    score = 0
    reason = ""
    try:
        ...
        cls_name = self.find_class_name(self.strategy_name)
        if cls_name is not None:
            ...
        else:
            logger.error(f"The specified strategy name : {self.strategy_name} could not be found.")
    except Exception as e:
        logger.error(f"[ERROR] : {e}")
    return score, reason
```

Note: the only signal of failure is a log line. The dashboard sees `score=0`, which is indistinguishable from "the model was bad".

## Suggested fix (small)

Either:

**(a) Register an explicit `AutoStrategy`** that dispatches to a sensible default — `similarity_match` for cases with `expected_output`, `llm_judge_positive` otherwise. ~20 lines.

**(b) Make missing strategies LOUD.** In `execute()`, when `cls_name is None`, either raise (and let the executor mark the case as `ERROR`, not `COMPLETED`) or return `(None, "STRATEGY_NOT_FOUND: ...")` so the dashboard can render it as an error rather than a zero score. ~5 lines.

I think (b) is the better fix even if (a) is also done — silent zeros are a much bigger problem than missing strategies, because they look real.

## Wider context

I found 15 other issues during the same source read. The class of problem ("silent failure dressed up as a numeric score") shows up in at least 4 strategies (`safety_strategy`, `bias_detection`, `hallucination_*`, `llm_judge_*`) — would be worth a small audit pass.

Confirmed against commit `<add the SHA you read>` of `main`.
