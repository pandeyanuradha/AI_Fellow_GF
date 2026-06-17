# WhatsApp Web path silently returns `"No response received"` for a working bot — three stacked stale-selector / fail-silent defects (with a verified fix)

I found this while running a real end-to-end evaluation through the **WhatsApp Web (Selenium) interface** — the third of the tool's three target types (`API`, `WEBAPP`, `WHATSAPP_WEB`). Exercised against a **real maternal-health WhatsApp Business bot** ("Khushi Baby Asha Saheli") from a personal WhatsApp account, scanning the QR through the bundled Selenium container's noVNC viewer.

The bot answered **correctly** every time. The tool reported `"No response received"` every time, with **HTTP 200**. Three defects stack up; the bot's real answer sits in the page DOM, unread.

## Summary

Driving one prompt through `POST /chat` with `application_type: WHATSAPP_WEB`:

| # | Where | Failure |
|---|-------|---------|
| A | `utils.py` `send_message_whatsapp` (response loop) | **Stale scrape selectors** — relies on `message-in` / `message-out` CSS classes and `data-testid='selectable-text'`, all of which current WhatsApp Web (Chrome 148, 2026) no longer emits. The 30 s wait matches **zero** elements → returns the literal string `"No response received"`. |
| B | `utils.py` `search_entity:412-414` | **Dead config** — the contact XPath is hardcoded from `config.json`'s `agent_name`; the documented `contact_selection_xpath` key in `xpaths.json` is silently ignored (a no-op knob). |
| C | `whatsapp.py` + `routers/common.py` `/chat` | **Fail-silent** — driver-init failure, contact-not-found, and scrape-timeout all return the *same* `"No response received"` string with **HTTP 200**, indistinguishable from a bot that genuinely said nothing. |

Net effect: a fully working WhatsApp chatbot is scored as returning **nothing**. An evaluator (or CI gate) built on this path would mark a correct bot as broken/empty — a false-negative that silently corrupts results.

## A — stale scrape selectors (the fatal defect)

[`src/app/interface_manager/xpaths.json`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/interface_manager/xpaths.json) (`whatsapp_web.ChatPage`):
```jsonc
"message_in_element":   "//div[... ' message-in ' ...]",
"message_out_element":  "//div[... ' message-out ' ...]",
"agent_response_element": ".//div[...'copyable-text'...]//span[@data-testid='selectable-text']"
```

The response loop in `send_message_whatsapp` waits on `message_in | message_out`:
```python
all_messages = wait.until(
    EC.presence_of_all_elements_located(
        (By.XPATH, f"{message_in} | {message_out}")   # matches NOTHING
    )
)
...
responses = [m for m in responses_after
             if "message-in" in str(m.get_attribute("class"))]   # never true
```

Probing the **live DOM** of the logged-in session, with the bot's answer on screen:
```
div.message-out count: 0
div.message-in  count: 0
```
Both classes are gone. WhatsApp also dropped `data-testid='selectable-text'`. So `all_messages` is empty, the loop times out after 30 s, and the function returns `"No response received"` — even though the answer is right there.

There is even an in-repo breadcrumb that this class of breakage is known:
```python
# @bugfix.  The XPath has changed! -- Sudar 02.08.2025
```

### What still works (the fix anchors)

Direction can't be read from a CSS class anymore, and it can't be read from a sender name either:
- **Outgoing** bubbles carry a `div[data-pre-plain-text]` child (`"[12:47 PM, 6/16/2026] Anuradha: "`) — but with the *linked account's own name*, not `"You"`.
- This **WhatsApp Business** bot's replies render as template/interactive messages with **no `data-pre-plain-text` at all**.

The one robust, observed invariant: **outgoing rows have `data-pre-plain-text`; the agent's reply is the set of `div[role=row]` rows after the last outgoing row that do *not* carry `data-pre-plain-text`.**

## B — `contact_selection_xpath` is dead config

[`src/app/interface_manager/utils.py:412-414`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/interface_manager/utils.py#L412-L414):
```python
entity_name = cfg.get("agent_name")                        # from config.json
contact_selection = "//span[@title='" + entity_name + "']" # hardcoded; ignores xpaths.json
```

`xpaths.json` defines a `contact_selection_xpath` under `whatsapp_web.ChatPage`, which reads like the knob you'd edit to target a contact — but `search_entity` never reads it. The first live run searched WhatsApp for the literal model id `qwen2.5:7b` (the `agent_name`) and failed with `search failed for 'qwen2.5:7b'`, despite `contact_selection_xpath` being set to the bot. The documented selector is a no-op.

## C — fail-silent: HTTP 200 + `"No response received"` for every failure mode

[`src/app/interface_manager/whatsapp.py`](https://github.com/cerai-iitm/AIEvaluationTool/blob/main/src/app/interface_manager/whatsapp.py) `send_prompt_whatsapp`:
```python
if not driver:
    return [{"chat_id": ..., "response": "No response received"} for p in prompt_list]
...
if not search_llm(driver):
    return [{"chat_id": ..., "response": "No response received"} for p in prompt_list]
```
and the scrape-timeout branch in `send_message_whatsapp` returns the same string. The `/chat` router then wraps all of it in `200 OK`. So **driver crash**, **contact not found**, **scrape failure**, and **bot genuinely silent** are all the same observable result. This is the same fail-open failure class as the WEBAPP `[Not available]` bug and bug #3 (empty refusal mislabelled): infrastructure failures are reported as model outputs.

## Reproduction

1. `config.json` → `application_type: WHATSAPP_WEB`, `agent_name: <exact chat title of a real bot>`, `whatsapp_url: https://web.whatsapp.com`, `selenium_mode: remote`.
2. `POST /chat {"chat_id": 1, "prompt_list": ["How often should I get antenatal check-ups during pregnancy?"]}`.
3. Scan the QR (noVNC at `:7900`). The bot receives the message and replies correctly **on screen**.
4. Observe: API returns `200 OK` with `"response": "No response received"`. Logs show `Chat attempt 1/2/3 failed: Message:` (empty Selenium timeout) → `Max chat retries reached`.

## Fix (verified live, end-to-end)

A patch implementing all three fixes is included at [`issues/patches/whatsapp-web-fix.patch`](patches/whatsapp-web-fix.patch). Summary:

- **A** — replace the class-based scrape with the `data-pre-plain-text` invariant:
  ```python
  row_xpath = "//div[@role='row']"
  pre_text_xpath = ".//div[@data-pre-plain-text]"
  def _is_outgoing(row):
      return bool(row.find_elements(By.XPATH, pre_text_xpath))
  outgoing_idxs = [i for i, r in enumerate(all_rows) if _is_outgoing(r)]
  last_index = outgoing_idxs[-1]
  responses = [r for r in all_rows[last_index + 1:]
               if not _is_outgoing(r) and (r.text or "").strip()]
  ```
  …and run each captured row through `clean_whatsapp_response()` to strip the avatar label, echoed prompt, timestamps, and suggestion chrome.
- **B** — honor the configured selector: `chat_cfg.get("contact_selection_xpath") or "//span[@title='" + entity_name + "']"`.
- **C** — raise a typed `WhatsAppInterfaceError` on driver/contact/scrape failure, and have `/chat` return **HTTP 502** for it, so the evaluator records a harness error instead of a scoreable empty answer.

### Verified result

| Stage | Before fix | After fix |
|-------|-----------|-----------|
| QR login | ✅ | ✅ |
| Contact search | ❌ searched `qwen2.5:7b` | ✅ opens the configured bot |
| Send message | ✅ | ✅ |
| **Scrape reply** | ❌ `"No response received"` (200) | ✅ returns the bot's real answer |
| Failure signalling | ❌ 200 for every failure | ✅ 502 `WhatsApp interface error` |

After the fix, the same prompt returned the bot's actual answer (HTTP 200):
> - First antenatal check-up: As soon as pregnancy is suspected or within the first 12 weeks
> - Second check-up: Between the 4th and 6th month of pregnancy
> - Third check-up: In the 8th month
> - Fourth check-up: In the 9th month

## Caveats / honest limitations

- The scraper reads a whole `div[role=row]`, whose innerText can include an avatar label (`"You"`), the echoed prompt (for quoted/reply bubbles), bare timestamps, voice-note durations, and suggestion labels (`"Related questions"`). A `clean_whatsapp_response()` helper in the patch strips those (the four-line answer above is the cleaned output); it is line-pattern based and may need extending for other bots' chrome.
- DOM-scraping `web.whatsapp.com` is inherently brittle (WhatsApp obfuscates and rotates its markup) **and** Selenium-driving WhatsApp violates its Terms of Service. The durable recommendation is fix **C** (fail loud) plus preferring the official **WhatsApp Business / Cloud API** over web-DOM scraping for any production evaluation harness.

## Why it matters

For a tool whose headline use case includes *"evaluate a deployed WhatsApp chatbot,"* the WhatsApp Web path reports a correct, grounded maternal-health bot as returning **nothing** — and does so with a success status code. The fix is verified end-to-end against a real bot; happy to open a PR.

---

Confirmed live against `v2.0` (commit `190c129`). The scrape/search bugs (A, B) and fail-silent design (C) are in upstream `utils.py` / `whatsapp.py` / `routers/common.py`. Test-only edits (`config.json`, `credentials.json`, contact name) were reverted after testing; the code fix is captured as a patch in this repo.
