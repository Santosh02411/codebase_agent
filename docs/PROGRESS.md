# Progress Tracker

**Current version:** v1 · **Last updated:** 2026-10-08

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
| 7 Product & production | ⬜ API only; UI, DB, auth pending |
| 8 Evaluation & observability | 🟡 retrieval metrics only |

## Done
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
- ✅ Test suite: 23 tests passing (parsing, retrieval, agent on both engines, API, eval)

## Written but untested
- 🟡 Gemini / OpenAI LLM classes and OpenAI / Gemini embedders — need API keys; default model names may be outdated, set `LLM_MODEL`
- 🟡 Real-LLM behaviour of the prompts (tests use a scripted LLM, so patch *quality* from a real model is unmeasured)
- 🟡 `git clone` path for GitHub URLs

## To do (priority order)
1. P1.4 Smoke test with a real Gemini/OpenAI key on a real repo; tune prompts
2. P8.2 Bigger eval set on real repos; compare hash vs OpenAI/Gemini embeddings
3. P5.4 Stack-trace parser → seed retrieval with file:line
4. P4.5 Native LLM function-calling so the model picks tools freely
5. P3.4 Tree-sitter parsing for JS/TS/Java/Go; P6.6 non-Python test runners
6. P6.3 Docker sandbox (no network, CPU/memory limits) — required before any public deployment
7. P7.2 PostgreSQL + pgvector (replace JSON/pickle), P7.9 background indexing
8. P3.5 Cross-encoder / LLM reranker
9. P5.5 Documentation search tool; P6.4 linter; P6.5 git diff tool
10. P7.8 GitHub API tools (issues, open a PR with the fix)
11. P7.4 Next.js UI (repo tree, chat, agent activity panel, Apply Fix)
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
- **v1** — Backend core: ingest, hybrid RAG, AST chunking, call graph, LangGraph agent, debug → patch → verify loop, API, eval, docs, Docker files
