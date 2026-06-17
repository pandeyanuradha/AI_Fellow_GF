"""
HTML report generator. Self-contained: one Jinja template, no external CSS.

The output is what goes on GitHub Pages as the "live findings endpoint".
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, BaseLoader, select_autoescape


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Maternal &amp; Child Health Q&amp;A — Evaluation Report</title>
<style>
:root {
  --green: #1a7f37;
  --red:   #cf222e;
  --amber: #9a6700;
  --bg:    #f6f8fa;
  --fg:    #1f2328;
  --muted: #656d76;
  --border: #d0d7de;
}
* { box-sizing: border-box; }
body { font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
       color: var(--fg); background: white; margin: 0; padding: 2rem;
       max-width: 1200px; margin-inline: auto; }
h1 { margin-top: 0; }
h2 { border-bottom: 1px solid var(--border); padding-bottom: 0.3rem; margin-top: 2rem; }
.subhead { color: var(--muted); margin-top: -0.5rem; margin-bottom: 1rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; }
.card { border: 1px solid var(--border); border-radius: 6px; padding: 1rem; background: var(--bg); }
.card .big { font-size: 1.8rem; font-weight: 600; }
.card .label { color: var(--muted); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; }
table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); vertical-align: top; }
th { background: var(--bg); font-weight: 600; }
.pass { color: var(--green); font-weight: 600; }
.fail { color: var(--red); font-weight: 600; }
.tag { display: inline-block; padding: 0 0.5rem; border-radius: 3px; font-size: 0.8rem;
       background: var(--bg); border: 1px solid var(--border); }
.tag.cat-factuality      { background: #ddf4ff; border-color: #54aeff; }
.tag.cat-safety_refuse   { background: #ffebe9; border-color: #ff8182; }
.tag.cat-safety_deflect  { background: #fff8c5; border-color: #d4a72c; }
.tag.cat-safety_answer   { background: #dafbe1; border-color: #4ac26b; }
.tag.cat-bias            { background: #fbefff; border-color: #c297ff; }
details { margin: 0.5rem 0; }
details > summary { cursor: pointer; color: var(--muted); }
code { background: var(--bg); padding: 0 0.3rem; border-radius: 3px; font-size: 0.9em; }
.response, .reason {
  white-space: pre-wrap; background: var(--bg); padding: 0.75rem; border-radius: 4px;
  border: 1px solid var(--border); font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 0.85rem; max-height: 300px; overflow: auto;
}
.fact-list { margin: 0; padding-left: 1.2rem; }
.fact-list li.contained { color: var(--green); }
.fact-list li.missing { color: var(--red); }
.meta { font-size: 0.85rem; color: var(--muted); }
.bar { height: 6px; background: var(--bg); border-radius: 3px; overflow: hidden; margin-top: 0.3rem; }
.bar > div { height: 100%; background: var(--green); }
</style>
</head>
<body>

<h1>Maternal &amp; Child Health Q&amp;A — Evaluation Report</h1>
<p class="subhead">
  Reference evaluator built as critique-companion to <a href="https://github.com/cerai-iitm/AIEvaluationTool">CeRAI AIEvaluationTool</a>.
  Demonstrates correct refusal handling (bug #3), multilingual bias detection (bug #5),
  and self-bias-free factuality (bug #4).
</p>

<h2>Summary</h2>
<div class="grid">
  <div class="card">
    <div class="label">Pass rate</div>
    <div class="big">{{ summary.passed_total }} / {{ summary.total_cases }}</div>
    <div class="bar"><div style="width: {{ (summary.passed_total / summary.total_cases * 100) | round(1) }}%"></div></div>
  </div>
  <div class="card">
    <div class="label">Endpoint</div>
    <div><code>{{ summary.endpoint }}</code></div>
    <div class="meta">target: {{ summary.target_model }}</div>
  </div>
  <div class="card">
    <div class="label">Judge model</div>
    <div><code>{{ summary.judge_model }}</code></div>
    <div class="meta">{% if summary.factuality_judge_enabled %}enabled (≠ target ✓){% else %}disabled — no API key{% endif %}</div>
  </div>
  <div class="card">
    <div class="label">Bias model</div>
    <div><code style="font-size: 0.75rem;">{{ summary.bias_model }}</code></div>
    <div class="meta">multilingual zero-shot</div>
  </div>
  <div class="card">
    <div class="label">Duration</div>
    <div class="big">{{ summary.duration_seconds }}s</div>
  </div>
</div>

<h2>By category</h2>
<table>
  <thead><tr><th>Category</th><th>Passed</th><th>Total</th><th>Rate</th></tr></thead>
  <tbody>
  {% for cat, stats in summary.by_category.items() %}
    <tr>
      <td><span class="tag cat-{{ cat }}">{{ cat }}</span></td>
      <td>{{ stats.passed }}</td>
      <td>{{ stats.total }}</td>
      <td>{{ ((stats.passed / stats.total) * 100) | round(0) | int }}%</td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<h2>Per-case results</h2>
<table>
  <thead>
    <tr>
      <th style="width: 8rem;">ID</th>
      <th>Question</th>
      <th style="width: 8rem;">Category</th>
      <th style="width: 6rem;">Result</th>
      <th style="width: 4rem;">Lang</th>
    </tr>
  </thead>
  <tbody>
  {% for r in summary.results %}
    <tr>
      <td><code>{{ r.case.id }}</code></td>
      <td>
        <div>{{ r.case.question }}</div>
        <details>
          <summary>Show details</summary>
          {% if r.error %}
            <div class="reason fail">ENDPOINT ERROR: {{ r.error }}</div>
          {% else %}
            <p><strong>Response:</strong></p>
            <div class="response">{{ r.response or "(empty response)" }}</div>

            <p><strong>safety_aware</strong>
              {% if r.metrics.safety_aware.passed %}<span class="pass">PASS</span>{% else %}<span class="fail">FAIL</span>{% endif %}
            </p>
            <div class="reason">{{ r.metrics.safety_aware.reason }}
expected behaviour: {{ r.metrics.safety_aware.expected }} | refusal kind: {{ r.metrics.safety_aware.refusal_kind }}</div>

            {% if r.metrics.factuality %}
              <p><strong>factuality</strong>
                score = {{ r.metrics.factuality.score | round(2) }}
                ({{ r.metrics.factuality.reason }})
              </p>
              <ul class="fact-list">
                {% for f in r.metrics.factuality.per_fact %}
                  <li class="{% if f.contained %}contained{% else %}missing{% endif %}">
                    {% if f.contained %}✓{% else %}✗{% endif %} {{ f.fact }}
                    <span class="meta"> — {{ f.reason }}</span>
                  </li>
                {% endfor %}
              </ul>
            {% endif %}

            {% if r.metrics.bias %}
              <p><strong>bias</strong>
                label = <code>{{ r.metrics.bias.label }}</code>
                {% if r.metrics.bias.score is not none %}
                  (biased p={{ r.metrics.bias.biased_prob | round(2) }},
                   not-biased p={{ r.metrics.bias.not_biased_prob | round(2) }})
                {% endif %}
              </p>
              <div class="reason">{{ r.metrics.bias.reason }}</div>
            {% endif %}
          {% endif %}
        </details>
      </td>
      <td><span class="tag cat-{{ r.case.category }}">{{ r.case.category }}</span></td>
      <td>
        {% if r.passed %}<span class="pass">PASS</span>{% else %}<span class="fail">FAIL</span>{% endif %}
      </td>
      <td><code>{{ r.case.language }}</code></td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<p class="meta" style="margin-top: 3rem;">
  Generated by <code>eval.runner</code>.
  Source: <a href="https://github.com/">github.com/&lt;your-handle&gt;/cerai-eval-assignment</a>.
</p>

</body>
</html>
"""


def render_html_report(summary: dict, out_path: Path) -> None:
    env = Environment(
        loader=BaseLoader(),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.from_string(_TEMPLATE)
    html = template.render(summary=summary)
    out_path.write_text(html, encoding="utf-8")
