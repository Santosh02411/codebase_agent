# Progress Tracker

**Current version:** v4 · **Last updated:** 2026-10-08

Legend: ✅ done & tested · 🟡 implemented, not yet verified with real services · ⬜ not started

## Status by phase
| Phase | Status |
|---|---|
| 1 Foundations | 🟡 mostly done (needs real-key smoke test) |
| 2 Repo ingestion + Code RAG | 🟡 done on local store; pgvector pending |
| 3 Code intelligence | 🟡 Python done; Tree-sitter pending |
| 4 Agent | 🟡 workflow done; native function-calling pending |
| 5 Debugging | 🟡 core loop done; stack-trace parsing pending |
| 6 Execution | 🟡 subprocess sandbox done; Docker sandbox pending |
| 7 Product & production | 🟡 API + basic web UI; DB, auth, Next.js pending |
| 8 Evaluation & observability | 🟡 retrieval metrics only |

## Done
### Added in v4
- ✅ Architecture overview (`/architecture`): folders, routes, internal import graph, deps; works offline, AI writes the narrative
- ✅ Code review (`/review`): AST/regex checks (bare except, mutable defaults, eval/exec, hard-coded secrets, long functions, TODOs) + AI findings
- ✅ Multi-file change engine (`/change`): edits + new files validated together, tested before/after in the sandbox, retried with test feedback, applied with `/apply-changes`
- ✅ Test generation (`/generate-tests`): one new test file, verified in the sandbox
- ✅ GitHub PR (`/create-pr`): branch + commits via the GitHub contents API, explicit `confirm`, token stays on the server
- ✅ UI: 7 modes, review list, multi-file diff view, Apply and Open-pull-request buttons, code viewer (`/repositories/{id}/file`)
- 🟡 PR flow tested against a mocked GitHub only; real-LLM quality of change/test/review prompts unmeasured

- ✅ P1.1 Project skeleton, env-based config
- ✅ P1.2 LLM abstraction `get_llm(provider)` with offline `mock` provider (Gemini/OpenAI classes written — see "Written but untested")
- ✅ P1.3 JSON extraction from LLM output (handles code fences / extra prose)
- ✅ P2.1 Ingest from GitHub URL (validated), local path (opt-in), zip upload (zip-slip safe) — URL clone path not exercised in tests (no network in tests)
- ✅ P2.2 File scan, requirements.txt / package.json parsing
- ✅ P2.3/P3.1 AST-aware Python chunking (functions, methods, class headers, module code); regex-based JS/TS chunking; line-window fallback
- ✅ P2.4 Hashing embedder (offline)
- ✅ P2.5 Hybrid search: BM25 + vectors + Reciprocal Rank Fusion, identifier- and stem-aware tokenizer
- ✅ P2.6 Lexical reranker (term coverage + symbol/path match)
- ✅ P3.2 Call graph (callers/callees) used to expand retrieved context
- ✅ P3.3 Python import → internal file resolution
- ✅ P4.1–P4.4 Agent state, query analysis, retrieve ⇄ analyze loop, tools, LangGraph workflow (+ built-in runner; both tested)
- ✅ P5.2/P5.3 Root-cause analysis and validated search/replace patch + unified diff
- ✅ P6.1/P6.2 Tests run in temp copy before and after patch; retry with test-failure feedback
- ✅ P7.1 REST API: /repositories, /upload, /search, /chat, /debug, /generate-fix, /run-tests, /apply-patch, /runs
- ✅ P8.1 Retrieval metrics (recall@k, precision@k, MRR) + 5-question dataset
- ✅ Test suite: 30 tests passing (parsing, retrieval, large-repo regression, agent on both engines, API incl. zip upload, eval)

### Added in v3
- ✅ **Web UI** served by the API at `/` (no Node/npm needed): upload zip or add GitHub URL, pick project, file browser, Search / Ask / Find-bug-and-fix modes, agent step timeline, sources, colored diff, before/after test verdict, Apply-fix and Run-tests buttons
- ✅ Retrieval: import-heavy chunks down-weighted; backend vs frontend bias from the wording of the question; HTTP-method words boost matching routes; regression test for "POST endpoint for bulk import" (backend handler must beat the frontend client function)
- 🟡 UI is a single static HTML page, tested for JS syntax and that it is served — not clicked through in a real browser by me. Next.js UI (P7.4) is still planned if a bigger app is wanted

### Added in v2 (from first real-repo run: 355 files / 2,796 chunks)
- ✅ Retrieval priors: docs, tests and config files are down-weighted unless the question asks for them; functions/methods outrank loose text blocks
- ✅ HTTP route metadata (`POST /deliveries`) extracted from FastAPI/Flask-style decorators (incl. router prefixes) and used in search + reranking + LLM context
- ✅ Stemmer handles `deliveries → delivery`
- ✅ `.env` now loads automatically (python-dotenv); tests are isolated from a developer's real `.env`
- ✅ Fixed zip upload (`SpooledTemporaryFile` error); zip upload test added
- ✅ Mock LLM no longer generates noisy single-word queries

## Written but untested
- 🟡 Gemini / OpenAI LLM classes and OpenAI / Gemini embedders — need API keys; default model names may be outdated, set `LLM_MODEL`
- 🟡 Real-LLM behaviour of the prompts (tests use a scripted LLM, so patch *quality* from a real model is unmeasured)
- 🟡 `git clone` path for GitHub URLs

## Observed on first real repo (v1) — and status
- Search on "where is delivery creation handled" returned FEATURE_LOG.md blocks, refund code and an unrelated screen instead of the create-delivery route → fixed by v2 priors/route metadata **on a synthetic repo; not yet re-measured on the real Delivery_Sync repo**
- Mock LLM `/debug` returns `no_fix` as expected (needs a real LLM to write a patch)

## To do (priority order)
1. P1.4 Smoke test with a real Gemini/OpenAI key on a real repo; tune prompts
2. P8.2 Labelled eval set built from the real Delivery_Sync repo (10–20 questions); measure recall@k before/after v2; compare hash vs OpenAI/Gemini embeddings
3. P5.4 Stack-trace parser → seed retrieval with file:line
4. P4.5 Native LLM function-calling so the model picks tools freely
5. P3.4 Tree-sitter parsing for JS/TS/Java/Go; P6.6 non-Python test runners
6. P6.3 Docker sandbox (no network, CPU/memory limits) — required before any public deployment
7. P7.2 PostgreSQL + pgvector (replace JSON/pickle), P7.9 background indexing
8. P3.5 Cross-encoder / LLM reranker
9. P5.5 Documentation search tool; P6.4 linter; P6.5 git diff tool
10. P7.8 GitHub API tools (issues, open a PR with the fix)
11. P7.4 Next.js UI upgrade (basic UI already shipped in v3)
12. P7.5 JWT auth + RBAC; P7.6 Redis; P7.7 CI; P7.10 deployment
13. P8.3–P8.6 Faithfulness metrics, agent metrics, LangSmith, dashboard
14. P4.6 Conversation memory

## Known limitations (v1)
- Index and registry are local files; single process
- Hash embeddings are mostly lexical
- Only Python projects can be verified with tests (pytest)
- Patch format is a single search/replace edit per attempt
- Sandbox is process-level isolation, not a container — do not run untrusted repos on a shared server yet

## Version history
- **v4** — Architecture, review, multi-file changes, test generation, GitHub PRs, modular frontend, 40 tests
- **v3** — Web UI at `/`, more retrieval priors (imports, backend/frontend, HTTP method), 30 tests
- **v2** — Retrieval quality fixes for large repos (priors, route metadata, stemming), auto `.env` loading, zip-upload fix, regression tests
- **v1** — Backend core: ingest, hybrid RAG, AST chunking, call graph, LangGraph agent, debug → patch → verify loop, API, eval, docs, Docker files
