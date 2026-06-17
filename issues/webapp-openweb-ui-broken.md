# WEBAPP/Selenium path is non-functional for `openweb-ui` (and `cpgrams`) yet returns HTTP 200 — a silent fail-open, plus two crashes on the way

I found this while running a real end-to-end evaluation through the **WEBAPP (Selenium) interface** — the same way the tool is meant to test a hosted web chatbot. The API/LOCAL paths have their own runtime crash (see *Executor response-shape* issue); this issue is the **web path**, exercised against a local [Open WebUI](https://github.com/open-webui/open-webui) instance running `qwen2.5:7b` via Ollama. Three defects stack up, and the worst one is invisible because the call still returns `200 OK`.

## Summary

Driving one prompt through `POST /chat` with `application_type: WEBAPP`, `application_name: openweb-ui`:

| # | Where | Failure |
|---|-------|---------|
| A | `webapp.py:92` | `KeyError: 'send_button_element'` — hard crash at login for `openweb-ui`/`cpgrams` |
| B | `webapp.py:93-94` | `TypeError: not all arguments converted during string formatting` — logging crash on **every** call |
| C | `webapp.py:96-103` | **Fail-open**: login fails (`login_ok=False`) but the endpoint returns `{"response": "[Not available]"}` with **HTTP 200** |
| D | `utils.py:598-614` | `send_message_webapp` only knows `farmerchat`; `openweb-ui`/`cpgrams` would `raise ValueError("Unsupported application")` even if login succeeded |

Net effect: the bundled `openweb-ui` web target **cannot be evaluated at all**, but a consumer of the API sees a successful response containing the placeholder string `[Not available]`, which an evaluator will score as a real (empty) answer.

## A — `KeyError: 'send_button_element'` (hard crash at login)

[`src/app/interface_manager/webapp.py:92`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/interface_manager/webapp.py#L92)
```python
login_ok = is_logged_in(driver, send_element=chat_cfg["send_button_element"]) or login_webapp(app_name)
```

`send_prompt` unconditionally reads `chat_cfg["send_button_element"]`, but the bundled `xpaths.json` defines that key for only **2 of 4** apps:

```
whatsapp_web   has send_button_element? True
farmerchat     has send_button_element? True
cpgrams        has send_button_element? False   ← ChatPage: profile_pic, prompt_input_box, agent_response
openweb-ui     has send_button_element? False   ← ChatPage: model_selection, model_name_entry, prompt_input_box, agent_response
```

So the WEBAPP path raises `KeyError` at login for `openweb-ui` and `cpgrams` — the request 500s before the browser ever does anything.

## B — logging `TypeError` on every WEBAPP call

[`src/app/interface_manager/webapp.py:93-94`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/interface_manager/webapp.py#L93-L94)
```python
logger.info("after function running xpath: ", chat_cfg["send_button_element"])
logger.info("login_ok:", login_ok)
```

These pass a value as a **second positional argument** to `logger.info`, which the stdlib logger treats as a `%`-format arg. With no `%s` in the message it raises, on every call:

```
--- Logging error ---
TypeError: not all arguments converted during string formatting
  ...
  logger.info("login_ok:", login_ok)
Message: 'login_ok:'
Arguments: (False,)
```

The run survives only because `logging` swallows formatting errors — but every WEBAPP request emits a stack trace into the logs (and, notably, line 94 also leaks that `login_ok` is `False`, see C).

## C — fail-open: HTTP 200 with `"[Not available]"`

[`src/app/interface_manager/webapp.py:96-103`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/interface_manager/webapp.py#L96-L103)
```python
for prompt in prompt_list:
    result = {"chat_id": chat_id, "prompt": prompt, "response": "[Not available]"}
    if login_ok:
        ...
        result["response"] = send_message_webapp(driver, app_name, prompt)
    results.append(result)
return results
```

After working around A, the live run produced:

```
[INFO] Chat request: WebApp openweb-ui
[INFO] Launching openweb-ui at http://host.docker.internal:3001
[INFO] Using Remote WebDriver at http://selenium-browser:4444/wd/hub
login_ok: False
INFO: 127.0.0.1 - "POST /chat HTTP/1.1" 200 OK
{"response":[{"chat_id":1,"prompt":"How often should I get antenatal check-ups?","response":"[Not available]"}]}
```

`is_logged_in` ([`utils.py:243-252`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/interface_manager/utils.py#L243-L252)) waits for the (wrong) element, times out, and returns `False`; `login_webapp` also fails to confirm login — so `login_ok` is `False`, the body of the loop is skipped, and the placeholder `"[Not available]"` is returned **with status 200**. There is no error signalling: the executor / evaluator downstream cannot tell a genuine empty answer from a total interface failure. This is the same fail-open failure mode as bug #3 (empty refusal mislabelled), but here it masks a complete inability to reach the target.

## D — only `farmerchat` is actually wired up

[`src/app/interface_manager/utils.py:598-614`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/interface_manager/utils.py#L598-L614)
```python
APP_HANDLERS = {
    "farmerchat": handle_farmerchat,
}

def send_message_webapp(driver, app_name, prompt=None, max_retries=3):
    app = app_name.lower()
    handler = APP_HANDLERS.get(app)
    if not handler:
        raise ValueError(f"Unsupported application: {app}")
```

Even if login were fixed, the only implemented send handler is `farmerchat` (a shadow-DOM iframe widget). `openweb-ui` and `cpgrams` have XPath entries and config presets but **no handler**, so they would `raise ValueError("Unsupported application: openweb-ui")`. The WEBAPP "support" for the two non-farmerchat apps shipped in `xpaths.json` is effectively dead.

## Reproduction

1. Run any web chatbot the tool claims to support — e.g. Open WebUI on `http://host.docker.internal:3001` backed by Ollama.
2. Point the interface-manager at it: `config.json` → `application_type: WEBAPP`, `application_name: openweb-ui`, `application_url: http://host.docker.internal:3001`; add `credentials.json` for `openweb-ui`.
3. `POST /chat {"chat_id": 1, "prompt_list": ["How often should I get antenatal check-ups?"]}`.
4. Observe: `KeyError: 'send_button_element'` (A). Work around the key, and you get `200 OK` with `"[Not available]"` and `login_ok: False` in the logs (B + C). Reaching `send_message_webapp` would raise `ValueError` (D).

## Fixes

- **A**: read the key defensively and fall back to the input box that *every* ChatPage defines:
  ```python
  send_el = chat_cfg.get("send_button_element") or chat_cfg["prompt_input_box_element"]
  login_ok = is_logged_in(driver, send_element=send_el) or login_webapp(app_name)
  ```
- **B**: use `%s` placeholders (or f-strings): `logger.info("login_ok: %s", login_ok)`.
- **C**: do not return `200` for a failed interaction. When `login_ok` is `False`, surface an explicit error (distinct status or an `error` field) so the executor records a real failure instead of a scoreable placeholder.
- **D**: either implement `openweb-ui`/`cpgrams` handlers or remove their presets from `xpaths.json`/config so the tool doesn't advertise support it doesn't have.

## Why it matters

For a tool whose headline use case is *"evaluate a deployed web chatbot,"* the WEBAPP path against a stock Open WebUI fails three different ways and — most dangerously — reports success while doing so. The fail-open (C) means a CI gate built on this would pass with `[Not available]` for every case.

---

Confirmed live against `v2.0` (commit `190c129`). `webapp.py`, `utils.py`, and `xpaths.json` were **unmodified** on disk (`git status` clean); only `config.json`/`credentials.json` were repointed at the local target. Worked around in-container to expose the downstream failures; happy to open a PR.
