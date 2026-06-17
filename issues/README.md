# Bug reports

Each file in this directory is one bug I discovered during my own
investigation of the CeRAI AIEvaluationTool — first by reading the source,
then by running the full stack end-to-end.

Every claim cites a specific file and line number in the CeRAI source, so each
report can be verified independently and, if useful, reported to the
maintainers as-is. The `# ...` heading at the top of each file is the suggested
report title.

| File | What's broken |
|------|---------------|
| [strategy-auto-silent-zero.md](strategy-auto-silent-zero.md) | Bug #1 — `strategy="auto"` default scores every unmarked case 0 |
| [strategy-env-mount.md](strategy-env-mount.md) | Bug #2 — unmounted `strategy/.env` crash-loops the backend |
| [refusal-as-error.md](refusal-as-error.md) | Bug #3 — empty-content refusals dropped as connection errors |
| [bias-detection.md](bias-detection.md) | Bug #5 — bias detector inverted in English, broken on Indic text |
| [three-fragility-bugs.md](three-fragility-bugs.md) | Three smaller silent-failure bugs in the lazy loader + safety strategy |
| [executor-response-shape.md](executor-response-shape.md) | Runtime crash: response parsed as string, indexed as list-of-dicts |
| [report-create-report-signature.md](report-create-report-signature.md) | Runtime crash: PDF report call signature doesn't match its method |
| [webapp-openweb-ui-broken.md](webapp-openweb-ui-broken.md) | WEBAPP/Selenium path non-functional for bundled presets, fails open with 200 |
| [whatsapp-web-scraper-broken.md](whatsapp-web-scraper-broken.md) | WhatsApp Web path returns "No response received" for a working bot (verified fix in `patches/`) |

## `patches/`

Verified, applyable fixes for bugs above, supplied as git diffs:

| File | Fixes |
|------|-------|
| [patches/whatsapp-web-fix.patch](patches/whatsapp-web-fix.patch) | WhatsApp Web scrape + fail-open ([whatsapp-web-scraper-broken.md](whatsapp-web-scraper-broken.md)) — verified end-to-end against a live bot |