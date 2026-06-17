# Three smaller fragility bugs in `_lazy_loader.py` + `safety.py`

I found these while investigating the silent-zero bugs (#1, #3). Bundling them here since they're small but compounding.

## 1. `LazyLoader.create_mapp()` silently skips classes with no `__init__` defaults

[`src/lib/strategy/_lazy_loader.py:39-45`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/lib/strategy/_lazy_loader.py#L39-L45)
```python
for (arg, val) in zip(
    body.args.args[-len(body.args.defaults):],
    body.args.defaults
):
```

If `body.args.defaults` is empty (no defaults declared), `-len(defaults) == 0`, so `body.args.args[0:]` returns the full args list but `body.args.defaults` is still empty → `zip(...)` yields nothing → no `name` extracted → strategy is discovered but never registered.

The class is then unreachable via `find_class_name(...)`, which returns `None` → caller silently returns `score=0`. Per bug #1.

**Fix:** add `if not body.args.defaults: continue` at the top of the inner loop, or — better — log a warning at registration time that the class will be ignored.

## 2. `LazyLoader.get_class()` error message uses `None` instead of the missing name

[`src/lib/strategy/_lazy_loader.py:64`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/lib/strategy/_lazy_loader.py#L64)

The exception is raised with `mod_name` which is `None` at that point in the control flow. The resulting log line reads:

> `ValueError: Class None not found in the package.`

This is useless for debugging, especially because the exception is then caught by the broad `except Exception` in `StrategyImplementor.execute()` and the score silently becomes 0.

**Fix:** use `class_name` (the variable actually being looked up) in the message:
```python
raise ValueError(f"Class {class_name!r} not found in the package src.lib.strategy")
```

## 3. `safety_strategy` silently scores 0 on any setup without a Sarvam GPU service

[`src/lib/strategy/safety.py:32-36`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/lib/strategy/safety.py#L32-L36)
```python
self.gpu_url = os.getenv("GPU_URL")
if not self.gpu_url:
    logger.warning("GPU_URL is not set in environment.")
```

The warning is logged at init time, but `evaluate()` proceeds anyway: `requests.post(f"{self.gpu_url}/safety_eval", ...)` becomes `requests.post("None/safety_eval", ...)` → exception → caught by `StrategyImplementor.execute()` → silent `score=0`.

This affects every macOS user (where the `sarvam-ai` compose profile requires NVIDIA GPU) and anyone who runs without standing up the optional Sarvam service. They see safety scores of 0 across the board — indistinguishable from "the model was unsafe".

**Fix:** raise in `__init__` if `GPU_URL` is missing, or fall back to a Python-side safety classifier:
```python
if not self.gpu_url:
    raise RuntimeError(
        "safety_strategy requires GPU_URL (the Sarvam safety service). "
        "Either start the sarvam-ai compose profile (requires NVIDIA GPU) "
        "or use efficacy_of_content_filtering as a CPU-only alternative."
    )
```

---

Confirmed against commit `<SHA>` of `main`. Happy to open a single PR if you'd prefer one PR per fix vs. one bundled PR — let me know.
