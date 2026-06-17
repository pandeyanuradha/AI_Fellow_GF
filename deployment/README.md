# Deployment guide

This project deploys to two free services:

1. **Hugging Face Spaces (Docker SDK)** — hosts the maternal-health Q&A endpoint.
2. **GitHub Pages** — hosts the findings document and the eval HTML report.

## Prerequisites

- A GitHub account
- A Hugging Face account ([huggingface.co](https://huggingface.co))
- A Groq account ([console.groq.com](https://console.groq.com)) — free, no card

You should already have your `GROQ_API_KEY` in `.env` locally.

---

## 1. Deploy the endpoint to Hugging Face Spaces

### One-time setup

1. Go to [huggingface.co](https://huggingface.co) and create a new Space:
   - Name: `maternal-health-qa` (or whatever)
   - SDK: **Docker**
   - Hardware: **CPU basic** (free tier)
   - Visibility: **Public**

2. In the Space settings, go to **Variables and secrets** and add:
   - Secret `GROQ_API_KEY` = your Groq key
   - (Optional) Variable `TARGET_MODEL` = `llama-3.3-70b-versatile`

### Push

Clone the empty Space repo and copy our files in:

```bash
# Replace <your-hf-username> with your Hugging Face username.
git clone https://huggingface.co/spaces/<your-hf-username>/maternal-health-qa hf-space
cd hf-space
cp -r ../../"AI Fellow"/{Dockerfile,requirements.txt,pyproject.toml,endpoint,common} .
cp ../../"AI Fellow"/deployment/README-hf-space.md README.md

git add -A
git commit -m "Initial deploy: maternal-health Q&A endpoint"
git push
```

The Space will build (~5-10 minutes the first time) and start serving at:

```
https://<your-hf-username>-maternal-health-qa.hf.space
```

Test it:

```bash
curl -X POST "https://<your-hf-username>-maternal-health-qa.hf.space/chat" \
     -H 'Content-Type: application/json' \
     -d '{"message": "How often should I get antenatal check-ups?"}'
```

---

## 2. Deploy the findings to GitHub Pages

### One-time setup

1. Create a public GitHub repo. Push this whole project to it (with `vendor/` gitignored).
2. In the repo settings → **Pages**:
   - Source: **Deploy from a branch**
   - Branch: `main`, folder: `/docs`
   - Save.

After ~1 minute, your findings doc will be live at:

```
https://<your-gh-username>.github.io/<repo-name>/
```

### Updating

`docs/` already has the rendered findings page and the eval report from the most recent run. To refresh:

```bash
python -m eval.runner --endpoint https://<your-hf-username>-maternal-health-qa.hf.space \
    --out docs/results
git add docs/
git commit -m "Refresh eval results"
git push
```

GitHub Pages will rebuild automatically.

---

## 3. Submission URLs

After both deploys, you have:

| Asset            | URL                                                                       |
| ---------------- | ------------------------------------------------------------------------- |
| Findings doc     | `https://<gh-user>.github.io/<repo>/`                                     |
| Eval report      | `https://<gh-user>.github.io/<repo>/results/report.html`                  |
| Live endpoint    | `https://<hf-user>-maternal-health-qa.hf.space/chat` (POST JSON)          |
| Endpoint Swagger | `https://<hf-user>-maternal-health-qa.hf.space/docs` (interactive UI)     |
| Source repo      | `https://github.com/<gh-user>/<repo>`                                     |
