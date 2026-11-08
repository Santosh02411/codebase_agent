# Progress Tracker

**Current version:** v21 (CodeScout AI: review-first interface, paste-code review, exports, CLI, benchmark, full documentation) · **Last updated:** 2026-11-04

Legend: **Implemented** = code exists · **Tested** = covered by the offline test suite (scripted LLM, local sandbox, fake docker) · **Validated** = run against a real service (real LLM, real Docker, real GitHub, browser).

## Test status
Offline suite: 480 passed, 38 skipped, 0 failed (32 test files, run in two groups on 2026-11-03 in a sandbox with `coverage` installed). Skips are tests that need optional services or packages missing there (e.g. PostgreSQL). Nothing below is "Validated" unless stated.

## Capability matrix
| Capability | Implemented | Tested offline | Validated with real services |
|---|---|---|---|
| Ingest (GitHub URL, ZIP, folder), incremental indexing, symlinks never followed | yes | yes | git clone path not run here |
| Code intelligence (ast + Tree-sitter ×8, call/import/inheritance graphs, impact) | yes | yes | no |
| Hybrid RAG (vectors + BM25 + RRF + rerank), pgvector store | yes | in-memory yes; pgvector tests skipped here | no |
| LLM layer (OpenAI/Gemini/mock, retries, fallback, JSON repair, tools, usage) | yes | scripted LLM only | **no real-provider run** |
| LangGraph agent, 18 tools, reflection loops, conversation memory | yes | yes | no |
| Debugging report, reproduction, regression-test verification | yes | yes | no |
| Multi-file patch engine, approval, revert, repair | yes | yes | no |
| Docker sandbox, fail-closed | yes | fake docker | **no real Docker run** |
| Quality dashboard (10 analyzers, coverage, score) | yes | yes | tools run in this environment only where installed |
| GitHub OAuth, PR analysis/review, issue fix, PR creation | yes | mocked GitHub | **no real GitHub run** |
| Next.js IDE | yes | API only | **not clicked through in a browser** |
| Evaluation harness (retrieval + agent outcomes) | yes | yes | offline/mock results only |

## Added in v13 (each has regression tests in `tests/test_v13_hardening.py`)
- Review findings: severity, confidence, evidence, remediation; fewer false positives (placeholder secrets, constant `eval`, test fixtures); deduplication; AI findings grounded against real lines.
- Patch guard: patches that swallow exceptions or add `noqa`/`type: ignore`/`nosec` are rejected without a model call.
- Prompt-injection hardening: untrusted-data rule in all prompts, injection-pattern flagging and labelling, secret masking in context.
- Citation checks for `file:line` references (grounded / unretrieved / invalid) with a warning on invalid ones.
- Symlink safety in indexing and local copy.
- Tool failures reported as `TOOL FAILED`; any tool exception handled; `MAX_RUN_SECONDS` limit and cancel hook in the runtime.
- Verification fixes: regression "passed after" requires the tests to have run; regression tests that fail only on a missing symbol do not count as reproduction; tests not run are never "fixed".
- Test selection from changed files and the import graph with a fast targeted gate.
- Agent-outcome metrics (`python -m app.rag.eval agent`): root-cause accuracy, citation validity, patch success, regression effectiveness, with offline-mock vs real-provider labelling.

## Web app redesign (v14)
Implemented: application shell (collapsible sidebar, topbar, project switcher, Ctrl+K command palette, notifications built from real conditions, profile/GitHub menu, live indexing status), design system, dark and light themes (persisted, no flash), and pages for dashboard, AI chat with real-event agent timeline, code explorer, interactive architecture graphs (React Flow), debugging, review, quality, patches, testing, GitHub and settings. Details: `frontend/README.md`. Served by the backend at `/` from the static export in `app/webapp` (rebuild with `scripts/build_frontend.sh`); the previous single-page UI is at `/classic` and the multi-tab IDE at `/workbench`.
Verified: `tsc --noEmit` and `next build` pass; every route returns 200 from the production server; the API endpoints the new pages call were exercised against a running backend with the offline mock (stats, tree, symbols, symbol detail, module/call/impact graphs, patches, quality, sandbox, auth, and the `/agent/stream` event shapes).
**Not verified:** no real browser session was available, so the UI has not been clicked through, visually inspected or tested at different screen sizes; Monaco, React Flow interaction, chart rendering, theme switching, and the layout of every page are unverified in a browser. No accessibility audit with assistive technology. No frontend unit or end-to-end tests exist yet. Chat history is session-only. Answers are not token-streamed (the backend streams events, not tokens).

## v21: review first
Code Review is the second sidebar item and has a **Review code** button and a live summary card at the top of the dashboard. Added: paste-code review, report export (Markdown, SARIF, JSON), command-line mode with exit codes for CI (`python -m app.review`), a measured benchmark (`python -m app.review.bench`: 53/53 seeded mistakes found, 0 high/medium false alarms on 247 files of working code), demo projects with deliberate mistakes (`examples/`), full README and docs (REVIEW_ENGINE.md, DEMO.md). Product renamed CodeScout AI.

## v19
- **Review understands React/JS projects:** import paths that do not resolve, named/default imports a module does not export, packages missing from package.json (typos like `reactt`), undefined identifiers, JSX components and hooks (`useSate`, `<Hedaer />`), precise location of unclosed JSX expressions. Validated on this project's own 138-file React/TypeScript frontend: 0 high/medium findings (no false positives), 1.8 s.
- **System map is component-level** (one box per code folder, one labelled arrow per pair), non-code files excluded; **Execution flow** has a dropdown of routes/entry points/most-called/all functions with search, and follows React components a function renders; **File structure** lists the complete working copy (assets, configs, docs), not only parsed code.
- **Faster runs:** default LLM timeout 30 s (was 60), 2 retries (was 3); an overloaded Gemini model triggers an immediate one-off try of the next-best model; plain Explain questions skip the two planning model calls (`FAST_PLANNING=false` restores them). In a real run the planning calls plus timeouts were ~125 s of 275 s.

## v17: strict review, readable diagrams, fixes
- **Strict review engine** (`app/review/`, `POST /repositories/{id}/review/static`, ~1 s for 100+ files, no model): Python via the real compiler plus a scope analyser (undefined names/typos with "did you mean", `self.x` attribute typos, standard-library attribute typos, imports of names/modules that do not exist in the project, wrong call arguments and unknown keywords, unused imports/variables, redefinitions, unreachable code, bug patterns, security rules, hard-coded secrets on the syntax tree); JS/TS/Java/Go/Rust/C/C++ syntax errors from Tree-sitter (missing/extra braces, brackets, quotes) plus JS pattern rules and probable misspellings; JSON, YAML, TOML, HTML, CSS structure. Every file is analysed (the old review looked at the first 40 files with a handful of patterns). Results state what was analysed per language and what static analysis cannot see.
- **Validated against false positives:** run on this project's own `app/` (126 files of working code): 0 high-severity findings.
- **Source sync:** the server reviews its COPY of the project. `GET /repositories/{id}/source-status` lists files changed in your original folder since import; `POST /repositories/{id}/refresh` re-copies (or re-clones) and re-indexes. The review page warns when your folder has changed. (Previously "Re-index" re-indexed the stale copy, so edits made in the original folder were never seen.)
- **Diagrams for understanding:** System map (components grouped by explicit role rules, arrows labelled with imported names / called functions), Execution flow (UML-style sequence diagram + flowchart from the real call order, `GET /repositories/{id}/flow`), File structure tree with parser annotations; 3D labels are now fixed-size and legible, with a folder jump menu.
- **Fixes:** the page no longer freezes after adding/removing a project (Radix menu was leaving `pointer-events: none` on the page; menus are non-modal and a safety net releases the page); IDE view and classic UI now have a "Back" button.

## v16: AI-first web app (see docs/FRONTEND_AUDIT.md)
- **3D architecture explorer** (React Three Fiber): the repository's folders, files, functions/classes, imports, calls, inheritance, tests and routes from the real parsed graph (`GET /repositories/{id}/graph/system`); verified vs inferred edges; enter folders, inspect files/functions, incoming/outgoing highlighting with moving direction markers, path tracing, search, filters, legend and onboarding, 2D fallback, reduced-motion support.
- **Eight architecture perspectives:** 3D system, folders, files, function calls, request flow, data models, tests-to-source, impact; **Explain with AI** for the architecture or a selected folder/file/symbol (`POST /explain`).
- **Real testing:** test discovery separate from execution, real command/exit code/stdout/stderr, per-test outcomes, tracebacks with file:line frames, recorded history (executed runs only), explicit "Not executed".
- **AI project understanding** (`POST /repositories/{id}/overview`): cited explanation from the agent with parser facts as context, cached per index version; refuses to fabricate with the offline mock.
- **Insights** (`GET /repositories/{id}/insights`): entry points, key modules, hub functions, external packages, untested modules, risks, project-specific suggested questions; no model needed.
- Backend tests: `tests/test_v16_real_data.py` (9 tests).

## Measured results
- Retrieval, offline hash embedder, 50 questions: best config MRR 0.339, Recall@5 0.420 (`eval/results/offline_baseline_codebase_agent.md`).
- Agent outcomes, offline mock, 4 cases on the `delivery_sync` fixture: expected file in context 4/4; all model-dependent metrics n/a (`eval/results/agent_offline_mock_delivery_sync.md`).
- No real-LLM, real-embedding or patch-success numbers exist yet.

## Remaining limitations
- Real-provider prompt quality unmeasured; run `python -m app.rag.eval agent ... --provider gemini` and a real-embedder sweep.
- Real Docker, real GitHub and browser flows unverified.
- Cancel hook is not wired to an API endpoint. The file-viewer endpoint does not refuse secret files (agent tools do).
- The exact source shown to the coder is not secret-masked (edits are matched literally).
- Static call-graph resolution is name-based; dynamic dispatch is only resolved when the name is unique.
- Single local user; no accounts, RBAC or hosted deployment.
- Injection pattern-flagging cannot catch every phrasing; approval and the sandbox are the backstops.

## History
v13 hardening and review/eval work (above) · v12 Docker sandbox, quality dashboard, git intelligence, GitHub workflows · v11 tool system, debugging agent, patch engine · v10 LLM layer and multi-specialist agent · v7 RAG pipeline and experiments · v6 repository management and code intelligence · v5 Next.js IDE · v4 architecture, review, change, tests, PRs · v3 web UI · v2 retrieval fixes · v1 backend core.
