# Build Plan — AI Codebase Intelligence & Debugging Agent

## 1. Goal
Connect a GitHub repo (or upload a zip), ask a question or paste an error, and get: relevant code retrieved,
a grounded explanation, a root cause, a generated patch, and an automated test verdict (before vs after the patch).

Positioning: an **agentic RAG** system, not "chat with your repo". Retrieval is one tool inside a plan → retrieve →
analyse → fix → verify loop.

## 2. Architecture
```
User ─► FastAPI ─► Agent graph (LangGraph, built-in runner fallback)
                     analyze_query ─► retrieve ─► analyze ──need more?──► retrieve (loop, bounded)
                                                    │
                                          debug intent only
                                                    ▼
                                    generate_fix ─► verify ──tests fail?──► generate_fix (bounded retries)
                                                    │
                                                    ▼
                                                 respond
Tools: search_code · read_file · find_symbol · get_dependencies · list_tree · run_tests · (patch/apply)
Retrieval: AST chunks ─► embeddings + BM25 ─► RRF fusion ─► reranker ─► call-graph expansion ─► dedup ─► context
Sandbox: copy repo to temp dir ─► apply patch ─► run pytest (timeout, secrets stripped)
```
Design rules: the original repo is never modified until the user approves a patch (`POST /apply-patch`);
`/chat` can never patch; all agent loops are bounded (`MAX_AGENT_STEPS`, `MAX_FIX_ATTEMPTS`).

## 3. Tech stack
| Layer | Choice | Notes |
|---|---|---|
| Language / API | Python 3.11+, FastAPI | |
| Agent | LangGraph (+ LangChain core), custom runner fallback | nodes are plain methods |
| LLM | Gemini / OpenAI behind `get_llm(provider)` | `mock` provider for offline dev & tests |
| Embeddings | hashing (offline) / OpenAI / Gemini | `EMBEDDING_PROVIDER` |
| Parsing | Python `ast`; regex for JS/TS; Tree-sitter planned | |
| Search | BM25 + dense vectors + RRF, lexical reranker | cross-encoder planned |
| Storage | v1 JSON + pickle → PostgreSQL + pgvector (Phase 7) | |
| Infra | Docker, docker-compose, GitHub Actions | |
| Frontend | v3: single-file web UI served by FastAPI at `/`; Next.js + TypeScript optional upgrade (Phase 7) | |
| Observability | LangSmith (Phase 8) | |

## 4. Folder structure
```
app/
  main.py            FastAPI routes (+ serves UI)
  static/index.html  web UI
  config.py          env settings
  services.py        repo registry + index cache
  ingest.py          clone / copy / unzip, file scan, index build
  sandbox.py         isolated test execution
  patching.py        search/replace edits, unified diff
  evaluation.py      retrieval metrics (recall@k, precision@k, MRR)
  llm/               base, mock, openai_llm, gemini_llm, get_llm()
  parsing/           chunker (AST-aware), deps
  retrieval/         embeddings, bm25, index (hybrid), reranker
  agent/             state, tools, nodes (+routing), graph
tests/               unit + e2e tests, fixtures/delivery_sync (repo with a planted bug)
eval/dataset.json    labelled retrieval questions
docs/                BUILD_PLAN.md, PROGRESS.md
```

## 5. API
| Method | Path | Purpose |
|---|---|---|
| POST | /repositories | clone GitHub URL, index |
| POST | /repositories/upload | upload zip, index |
| GET | /repositories, /repositories/{id}/tree | list / file tree |
| POST | /repositories/{id}/index | re-index |
| POST | /search | hybrid search + rerank |
| POST | /chat | answer questions (no code changes) |
| POST | /debug | full loop: root cause → patch → tests before/after |
| POST | /generate-fix | patch without running tests |
| POST | /run-tests | run repo tests in sandbox |
| POST | /apply-patch | apply an approved patch, re-index |
| GET | /runs/{id} | saved agent run with step log |

## 6. Data model (target, Phase 7)
users, repositories, repository_files, code_chunks (+ `embedding vector(N)`, GIN index for keyword search),
conversations, messages, agent_runs, tool_calls, test_results. v1 equivalents: `repos.json`, `indexes/*.pkl`, `runs/*.json`.

## 7. Phases
Each task has an ID that PROGRESS.md tracks.

**Phase 1 — Foundations**: P1.1 project skeleton/config · P1.2 LLM abstraction (Gemini/OpenAI/mock) · P1.3 structured JSON output parsing · P1.4 real-provider smoke test with API keys

**Phase 2 — Repository ingestion + Code RAG**: P2.1 clone/copy/zip ingest · P2.2 file scan, deps · P2.3 chunking · P2.4 embeddings · P2.5 hybrid search (BM25 + vectors + RRF) · P2.6 reranker · P2.7 pgvector store

**Phase 3 — Code intelligence**: P3.1 Python AST chunking · P3.2 call graph (callers/callees) · P3.3 import/dependency resolution · P3.4 Tree-sitter for JS/TS/Java/Go · P3.5 cross-encoder / LLM reranker · P3.6 symbol-level graph for class hierarchies

**Phase 4 — Agent**: P4.1 agent state · P4.2 query analysis + planner · P4.3 tools · P4.4 LangGraph workflow with bounded loops · P4.5 native LLM function-calling (model picks tools freely) · P4.6 conversation memory

**Phase 5 — Debugging**: P5.1 error/stack-trace analysis · P5.2 root-cause reasoning · P5.3 patch generation (validated search/replace edits + unified diff) · P5.4 stack-trace parser that seeds retrieval with file:line · P5.5 documentation search tool

**Phase 6 — Execution**: P6.1 test runner in temp copy · P6.2 before/after verification + retry loop · P6.3 Docker-based sandbox (no network, resource limits) · P6.4 linter tool · P6.5 git diff inspection · P6.6 multi-language test runners (npm test, go test)

**Phase 7 — Product & production**: P7.1 REST API · P7.2 PostgreSQL + pgvector · P7.3 Dockerfile + compose · P7.4 Next.js UI (repo tree, chat, agent activity, apply-fix) · P7.5 JWT auth + RBAC · P7.6 Redis (cache, jobs) · P7.7 GitHub Actions CI · P7.8 GitHub API tools (issues, PRs, open PR with fix) · P7.9 background indexing jobs · P7.10 cloud deployment

**Phase 8 — Evaluation & observability**: P8.1 retrieval metrics · P8.2 larger multi-repo eval set · P8.3 answer faithfulness/relevance (LLM-judge or RAGAS) · P8.4 agent metrics (task success, steps, latency, tokens, cost) · P8.5 LangSmith tracing · P8.6 evaluation dashboard

## 8. Risks & mitigations
- **LLM emits an invalid patch** → edits must match exactly once; invalid edits are rejected and retried with feedback.
- **Running untrusted repo code** → temp copy, timeout, secrets stripped (v1); Docker with no network (P6.3). Do not expose publicly before P6.3.
- **Weak embeddings** → hashing embedder is lexical; use OpenAI/Gemini embeddings for semantic recall and measure with the eval set.
- **Infinite agent loops** → hard caps on retrieval rounds and fix attempts.
- **Prompt injection from repo content** → treat retrieved code as data; keep tools least-privilege; add output checks (Phase 7/8).
