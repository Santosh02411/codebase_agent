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

## Repository management & code intelligence (v6)
**Import** from GitHub (sign-in with OAuth, then pick any repo including private ones), any Git URL (GitLab and Bitbucket work; private ones via token in `.env`), ZIP, or a local folder. Choose the **branch** at import; later switch branch or analyse a specific **commit** from the Repository panel. After an import the dashboard shows files, languages, functions, classes, dependencies, tests, API endpoints, DB models and indexing status.

**Incremental indexing:** each file is hashed; only changed files are re-parsed and only new code is re-embedded. Switching branches re-processes just the files that differ (the report shows e.g. "3 files reprocessed, 120 reused").

**Code understanding, not fixed-size chunks:** Python uses the standard `ast` module; JavaScript, TypeScript/TSX, Java, C, C++, Go and Rust use Tree-sitter (Python files with syntax errors fall back to Tree-sitter too). Extracted per file: functions, classes, methods, interfaces/traits/structs/enums, variables, imports, doc comments, TODOs, API routes (Flask, FastAPI, Django, Express, NestJS, Spring, JAX-RS, Go net/http & gin/echo/chi, Actix/Rocket/Axum), ORM models (Django, SQLAlchemy, TypeORM, Mongoose/Sequelize, JPA, GORM, Diesel/SQLx) and test cases. From those the engine builds a **call graph**, **import/module graph**, **inheritance graph** and **impact analysis**. The agent receives these relationships with the code it retrieves, and can call `callers`, `callees` and `impact` as tools.

Known limits: resolution is static and name-based, so dynamic dispatch, reflection, decorators that rewrite calls, and calls through untyped variables are only resolved when the method name is unique (those edges are marked "guessed by name"). Go/Rust cross-file `impl` blocks and TypeScript path aliases other than `@/` are not followed. Other languages (C#, Ruby, PHP, Kotlin…) are indexed as text; adding one means adding a grammar package and a visitor in `app/intel/ts_langs.py`.

**GitHub sign-in:** create an OAuth App (callback `http://localhost:8000/auth/github/callback`) and set `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`. The token is stored in `data/auth.json` (mode 0600), never sent to the browser, and passed to git through the environment. This server assumes **one local user**; add real accounts before exposing it on a network.

## RAG pipeline & retrieval experiments (v7)
Hybrid retrieval (vector search + BM25 fused with Reciprocal Rank Fusion) → reranking → token-budgeted context with `[n]` citations that are validated against what the model was shown. Storage is **PostgreSQL + pgvector** when `DATABASE_URL` is set (`docker compose up db`), otherwise in-memory. Embedding providers: OpenAI (and OpenAI-compatible servers), Gemini, local BGE/sentence-transformers or fastembed, plus an offline hashing baseline. Rerankers: heuristic, cross-encoder (BGE reranker), LLM.

`python -m app.rag.eval run --repo . --dataset eval/datasets/codebase_agent.jsonl --preset offline` measures Recall@K, Precision@K, MRR, NDCG, Context Precision and Context Recall with confidence intervals; the **Experiments** view in the UI runs and browses the same experiments. Architecture, schema, metric definitions, how to compare real models, and baseline results: [docs/RAG.md](docs/RAG.md).

## Pushing to GitHub
`venv/`, `.env` and `data/` are git-ignored. Never commit the virtual environment; others recreate it from `requirements.txt`.
