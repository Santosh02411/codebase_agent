# Build Plan and Architecture (CodeScout AI v21)

## 1. Goal
Connect a repository (GitHub URL, ZIP, local folder), ask a question, paste an error or open a pull request, and get: relevant code retrieved, a grounded and cited explanation, a root cause, a multi-file patch, an automated before/after test verdict, and a code review. Nothing is applied or published without human approval.

Positioning: an **agentic RAG** system, not "chat with your repo". Retrieval is one tool inside a plan → investigate → analyse → fix → verify → review loop.

## 2. Architecture as implemented
```
repo ─► ingest (git / ZIP / folder; symlinks never followed) ─► parse (Python ast, Tree-sitter ×8)
      ─► chunks + symbols + call/import/inheritance graphs ─► embeddings + BM25 ─► PostgreSQL+pgvector (or in-memory), incremental by file hash

request ─► FastAPI ─► LangGraph workflow (built-in loop as fallback)
   understand ─► plan ─► research ⇄ analyze ─► code ─► test ─► (reflect ─► code | research) ─► review ─► document ─► respond
   Planner      Planner  Researcher  Debugger  Coder   Tester     Debugger                     Reviewer  Documenter
   PR mode: research ─► pr (analysis or review draft) ─► respond
```
- **LLM layer** (`app/llm/`): OpenAI, Gemini, or offline mock behind one interface; retries, fallback, JSON repair, function calling, token/latency/cost tracking, per-run call budget.
- **Tools** (`app/agent/registry.py`): 18 model-callable tools (search, symbols, grep, call graph, git history, config, docs, optional web, sandboxed tests/linter, patch generation/check). A failing tool returns `TOOL FAILED - ...`; results are secret-masked.
- **Context** (`app/agent/context.py`, `app/rag/context.py`): ranked evidence under a token budget, `[n]` citations, call-graph relationships, history. Repository text is untrusted: injection-like snippets are labelled, secrets masked.
- **Patching** (`app/patchset.py`, `app/patching.py`): multi-file edits, syntax-checked, atomic, with undo. Applied only after explicit approval.
- **Verification** (`app/verify.py`): baseline, regression-test reproduction on the original code, patched run. Targeted tests (`app/quality/select.py`) run first as a fast gate. Verdicts: resolved, partial, no_regressions, unverified, not_resolved.
- **Strict review engine** (`app/review/`): deterministic, whole-project, no model: Python compiler + scope analyser, Tree-sitter for JS/TS/JSX/Java/Go/Rust/C/C++, data/markup validators; details in REVIEW_ENGINE.md. The agent's Review mode runs it over every file.
- **Review** (`app/agent/checks.py`, Reviewer, PRReviewer): deterministic checks, AI review, deduplication, grounding; patch guard against exception-swallowing and lint-suppression patches.
- **Sandbox** (`app/sandbox_exec.py`): the only place repository code runs; Docker (no network, read-only FS, no privileges, hard timeout) or refuse (fail-closed). See SANDBOX.md.
- **Quality** (`app/quality/`): test runners for pytest/Jest/Vitest/Mocha/Go/Cargo/Maven/Gradle, coverage, 10 analyzers, one score.
- **GitHub** (`app/github_api.py`, `github_pr.py`, `pr_context.py`): OAuth, PR analysis/review, issue fixing, branch/commit/push/PR behind approval tickets.
- **Evaluation** (`app/rag/eval/`): retrieval metrics with confidence intervals, plus agent-outcome metrics (`agent_metrics.py`) with offline-mock vs real-provider provenance.
- **Interfaces**: Next.js IDE (`frontend/`, Monaco, live agent activity via SSE) and a single-page UI served at `/`.

## 3. Tech stack
Python 3.11+, FastAPI, LangGraph + LangChain core, Gemini/OpenAI, PostgreSQL + pgvector, BM25 + RRF, heuristic/cross-encoder/LLM rerankers, Python `ast` + Tree-sitter, Docker, Next.js/TypeScript.

## 4. Design rules
- The working copy is never modified until the user approves a patch; `/chat` can never patch.
- Every agent loop is bounded (`MAX_AGENT_STEPS`, `MAX_FIX_ATTEMPTS`, `MAX_TOOL_CALLS`, `MAX_AGENT_TOTAL_STEPS`, `MAX_LLM_CALLS`, `MAX_RUN_SECONDS`).
- Deterministic checks come before model calls (syntax, secrets, `eval`, swallowed exceptions).
- A fix is "resolved" only when a regression test fails before and passes after; otherwise it is reported as unverified, with the reason.
- Metrics are reported only when measured, and labelled offline/mock or real-provider.

## 5. Folder structure
```
app/            main.py (routes) · config.py · services.py · ingest.py · sandbox*.py · verify.py · patch*.py · github*.py · pr_context.py
  agent/        state, nodes (+routing), graph, specialists, registry (tools), context, checks, extras (secrets, injection), errors, trace, memory
  llm/          base, openai_llm, gemini_llm, mock, usage, types
  intel/        Python ast + Tree-sitter extraction, graphs, incremental store
  rag/          embedders, pg store, retriever, fusion, rerank, context, experiments, eval/ (metrics, runner, agent_metrics, CLI)
  quality/      frameworks, runner, analyzers, coverage, score, select (test selection)
frontend/       Next.js IDE
sandbox/        Dockerfiles per language + offline Semgrep rules
tests/          offline suite; fixtures/delivery_sync (planted bug)
eval/           datasets, configs, results
docs/           AGENT.md · RAG.md · SANDBOX.md · BUILD_PLAN.md · PROGRESS.md
```

## 6. What is not planned or not done
Real-provider quality measurement, real-Docker and real-GitHub end-to-end runs, JWT/RBAC multi-user accounts, Redis, CI, hosted deployment, LangSmith tracing, faithfulness metrics. See PROGRESS.md.
