# AI Codebase Intelligence & Debugging Agent

Agentic RAG over a code repository: index → hybrid retrieval → reasoning → patch → test verification.
Build plan and status live in [`docs/`](docs/BUILD_PLAN.md) · [`docs/PROGRESS.md`](docs/PROGRESS.md).

## Run
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # defaults to the offline mock LLM
uvicorn app.main:app --reload   # open http://localhost:8000 (UI); API docs at /docs
pytest                          # 30 tests
python -m app.evaluation --repo tests/fixtures/delivery_sync   # retrieval metrics
```
With a real model: set `LLM_PROVIDER=gemini|openai`, the API key, and `LLM_MODEL`.
The `mock` provider only does retrieval-based answers — patch generation needs a real LLM.

## IDE frontend (v5)
A Next.js workspace with editor, AI chat, search, git changes, terminal, test results, live agent activity and a diff viewer lives in [`frontend/`](frontend/README.md).
```bash
cd frontend && cp .env.example .env.local && npm install && npm run dev   # http://localhost:3000
```
The original single-page UI at http://localhost:8000 still works.

## Try it
```bash
curl -X POST localhost:8000/repositories -H 'content-type: application/json' \
  -d '{"source":"https://github.com/<owner>/<repo>"}'
curl -X POST localhost:8000/debug -H 'content-type: application/json' \
  -d '{"repo_id":"<id>","question":"500 error when creating a delivery"}'
```
Local folders need `ALLOW_LOCAL_PATHS=true`. Run `/debug` only on repos you trust until the Docker sandbox lands (P6.3).

## What it can do (v4)
| Capability | Mode in the UI | Endpoint |
|---|---|---|
| Answer code questions (RAG) | Ask / Search code | `/chat`, `/search` |
| Explain architecture | Architecture | `/architecture` |
| Debug an error, propose a verified fix | Find bug and fix | `/debug` |
| Generate code, change several files | Change code | `/change` then `/apply-changes` |
| Generate tests for a file | Write tests | `/generate-tests` |
| Run tests in a sandbox copy | Run tests | `/run-tests` |
| Review code (automatic checks + AI) | Review code | `/review` |
| Open a GitHub pull request | button on a change | `/create-pr` (needs `GITHUB_TOKEN`, project added from a GitHub URL) |
Code changes are always tested before and after in a throwaway copy, and nothing touches your project until you click Apply.

## Pushing to GitHub
`venv/`, `.env` and `data/` are git-ignored. Never commit the virtual environment; others recreate it from `requirements.txt`.
