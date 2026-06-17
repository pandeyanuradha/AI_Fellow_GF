# PDF report generation is dead code — `report.py` calls `create_report()` with a signature that doesn't exist

I found this while generating the report for a real end-to-end run. The console/JSON summary works, but `--get-report` (PDF) crashes immediately. The call site and the method definition have **drifted apart** — the caller was written against a newer intended signature that was never implemented on the method.

## Symptom

```
TypeError: create_report() got an unexpected keyword argument 'target_summary'
```

(Followed, once that is fixed, by further mismatches — see below. The whole PDF path is unreachable.)

## Root cause: caller vs. definition signature mismatch

### The caller

[`src/app/response_analyzer/report.py:314-326`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/response_analyzer/report.py#L314-L326)
```python
filename = EvaluationReport.create_report(
    target_name=target_name,
    run_name=run_name,
    timestamp=timestamp,
    total_testcases=total_testcases,
    target_summary=run_summary,      # (1)
    plan_summary=plan_summary,       # (2)
    score_card=score_card,
    out_path=os.path.join(...),      # (3)
    column_widths=[...] ,            # (4)
)
```

### The definition

[`src/lib/strategy/utils_new.py:685-696`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/lib/strategy/utils_new.py#L685-L696)
```python
def create_report(
    self,                # (5) instance method
    target_name,
    run_name,
    timestamp,
    total_testcases,
    run_summary,         # vs. caller's target_summary  (1)
    headers,             # caller never passes headers/rows  (2)
    rows,
    score_card,
    output_file          # vs. caller's out_path  (3)
):
```

The mismatches:

1. `target_summary=` → method parameter is `run_summary`.
2. `plan_summary=` → no such parameter; method expects `headers` and `rows`, which the caller never supplies.
3. `out_path=` → method parameter is `output_file`.
4. `column_widths=` → no such parameter on the method at all.
5. `create_report` is an **instance** method (`self`), but it is called statically as `EvaluationReport.create_report(...)` with no instance, so `self` is unbound.

So even after renaming `target_summary`→`run_summary`, the call still fails on `plan_summary`/`out_path`/`column_widths` and the missing required `headers`/`rows`/`output_file`. The PDF path has clearly never run against this version of `EvaluationReport`.

## Reproduction

```
python3 src/app/response_analyzer/report.py --config config.json \
    --run-name demo --get-report
```
→ `TypeError: create_report() got an unexpected keyword argument 'target_summary'`

(Omitting `--get-report` works, because the function returns early at
[`report.py:303-307`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/response_analyzer/report.py#L303-L307) before reaching the PDF block — which is how the console/JSON report still succeeds.)

## Fix

Reconcile the two. Either update the method to the caller's intended richer signature (it references `plan_summary`, `column_widths`, multi-plan layouts):

```python
@staticmethod
def create_report(target_name, run_name, timestamp, total_testcases,
                  target_summary, plan_summary, score_card, out_path,
                  column_widths=None):
    ...
```

or update the caller to the existing signature (build `headers`/`rows`, pass `run_summary`/`output_file`, and call on an instance). A regression test that actually invokes `--get-report` on a tiny finished run would have caught this and keeps the two in sync.

## Why it matters

The PDF report is the headline deliverable of the analyzer, and it cannot be produced at all on `main`. The bug is invisible without the `--get-report` flag, so a quick demo (console only) hides it.

---

Confirmed live against `main` (commit `<SHA>`). Worked around by using the console/JSON report.
