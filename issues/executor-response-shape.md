# Executor crashes with `string indices must be integers` after every successful generation (API + LOCAL interface)

I found this while running a real end-to-end evaluation (Guardrails & Safety plan, API interface, local Ollama target). This is a **runtime-only** bug: it does not show up in source review or unit tests, only when an agent actually returns a non-empty response. Every API/LOCAL test case crashes **after** the model has already answered, so a working pipeline looks broken.

## Symptom

```
TypeError: string indices must be integers, not 'str'
```

raised from `testcase_executor/main.py` immediately after a successful `client.chat(...)` call. The conversation row is left dangling and the run aborts.

## Root cause: half-finished refactor of the response shape

The response parser was updated to **flatten** the agent response into a plain **string**, but two downstream consumers were never updated and still treat it as the old **list-of-dicts** shape.

### The parser produces a string

[`src/app/testcase_executor/main.py:458-472`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/testcase_executor/main.py#L458-L472)
```python
data = response_from_agent.json().get("response")
agent_response = ""

if isinstance(data, list) and data:
    data = data[0].get("response", {})

if isinstance(data, dict):
    if data.get("type") == "text":
        agent_response = data.get("content", "")   # <-- agent_response is now a STRING
    elif data.get("type") == "audio":
        agent_response = data.get("file", "")       # <-- also a STRING
    else:
        agent_response = ""
```

After this block `agent_response` is unambiguously a `str` (or `""`).

### Consumer #1 — `is_error_response()` indexes it as a list-of-dicts

[`src/app/testcase_executor/main.py:26-33`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/testcase_executor/main.py#L26-L33)
```python
def is_error_response(response):
    error_indicators = [ ... ]
    return len(response) == 0 or any(
        indicator in response[0]['response'].lower()   # <-- response[0] is the first CHARACTER
        for indicator in error_indicators
    )
```

Called at [line 477](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/testcase_executor/main.py#L477) with the string. For a non-empty answer `"Antenatal..."`, `response[0]` is `"A"` and `"A"['response']` raises `TypeError: string indices must be integers, not 'str'`. (An empty answer accidentally survives because the short-circuit `len(response) == 0` returns first — so the bug only bites on **successful** generations.)

### Consumer #2 — the store site indexes it the same way

[`src/app/testcase_executor/main.py:483`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/testcase_executor/main.py#L483)
```python
conv.agent_response = agent_response[0]['response']   # same wrong assumption
```

The identical pattern is duplicated in the other two interface branches:
[line 612](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/testcase_executor/main.py#L612) and
[line 723](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/testcase_executor/main.py#L723).

## Reproduction

1. Bring up the stack, seed a target + a Guardrails/Safety plan, point the target at any agent that returns a normal text answer (we used a local Ollama `qwen2.5:7b` behind the interface-manager).
2. Run the executor:
   ```
   python3 src/app/testcase_executor/main.py --config config.json \
       --testplan-id <id> --run-name demo --run-continue --execute
   ```
3. The model answers, then the run dies with `string indices must be integers, not 'str'`.

## Fix

Make both consumers string-aware (they already receive a string):

```python
def is_error_response(response: str) -> bool:
    if not response:
        return True
    text = response.lower()
    return any(indicator in text for indicator in error_indicators)
```

and at the three store sites:

```python
conv.agent_response = agent_response   # it is already the text
```

## Why it matters

Because the crash happens **after** a correct generation, the tool is unusable for exactly the case it is meant to evaluate (an agent that responds). The three duplicated store sites also argue for factoring the response-handling block into one helper so a shape change can't drift again.

---

Confirmed live against `main` (commit `<SHA>`). Fixed ephemerally in-container to complete our run.
