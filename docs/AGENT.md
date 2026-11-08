# LLM layer and agent workflow (v10)

## 1. LLM layer — `app/llm/`

```
get_llm("gemini" | "openai" | "mock")  ──►  LLM  (base.py: everything shared)
                                              ├─ OpenAILLM   chat completions, tools, JSON mode, any OpenAI-compatible base_url
                                              ├─ GeminiLLM   google-genai, function declarations, JSON mime type
                                              └─ MockLLM     offline, deterministic (no keys, no patches)
```
A provider implements **one** method, `_complete(request, model) -> LLMResponse`. Everything else is written once in `base.py`.

| Concern | Where / how |
|---|---|
| Switching models | `LLM_PROVIDER`, `LLM_MODEL`, or `get_llm("openai", "model")` per call; the API takes `provider` per request |
| Model selection | `LLM_MODEL_FAST` serves planning, tool choice, reflection and short decisions (`TASK_TIER` in `base.py`); `LLM_MODEL` serves analysis, code and review. Unset = one model for all |
| Prompt engineering | One system prompt per role (`agent/prompts.py`); every JSON reply is described in the prompt, e.g. `Return JSON: {...}` |
| Structured / JSON output | JSON mode on both providers + pydantic validation (`agent/schemas.py`, lenient: coerces and defaults). Invalid reply → **one repair turn** quoting the problem → `LLMInvalidOutput` |
| Function calling | `LLMRequest(tools=[ToolSpec])` → `LLMResponse.tool_calls`. Messages carry `tool_calls` / tool results in a neutral format that each provider maps to its wire format. Gemini's own content object is echoed back verbatim (thought signatures) |
| Token tracking | Provider-reported usage per call; counted by us (flagged `estimated`) when absent. `llm.usage.summary()`: calls, in/out tokens, per task, per model |
| Latency | Per call, total, average and p95; the response also carries `latency_ms` |
| Cost | Only if you set `LLM_PRICES='{"model": [usd_per_1M_in, usd_per_1M_out]}'`. Nothing is hard-coded because prices change |
| Errors | `classify_exception` maps any SDK error to `LLMRateLimit / LLMTimeout / LLMUnavailable` (retried, exponential backoff + jitter, honours `Retry-After`) or `LLMAuthError / LLMBadRequest / LLMContextTooLong` (not retried) |
| Fallback | `LLM_FALLBACK=provider[:model]` is tried once the primary has used its retries. Only attached when that provider has a key |
| Budget | `MAX_LLM_CALLS` per run (default 40) → `LLMBudgetExceeded` |
| Observability | `llm.set_observer(cb)`: start / error / end / repair events with tokens and ms → the live Agent Activity panel. `GET /llm/usage` (process totals), `GET /llm/info` |

Parameters that some models reject (a custom `temperature` on reasoning models, `max_completion_tokens` on older compatible servers) are handled by omission or one retry without the parameter.

## 2. Context construction — `app/agent/context.py`

The repository is never sent to the model. Each call gets:

1. **Evidence**, gathered by the researcher: stack-trace frames (`agent/trace.py` parses Python, JS/TS, Java, Go, Rust traces and maps them to repo files), symbols the user named, hybrid search hits (vectors + BM25 + rerank), grep hits, call-graph neighbours (`callers`/`callees`), file ranges the model chose to read.
2. **Re-ranking** by signal: trace frame (+4) > named symbol (+2.5) > named file (+1.5) > search score; tests are down-weighted unless relevant.
3. **Packing** under `CONTEXT_TOKEN_BUDGET` (`rag.context.build_pack`): overlap removal, per-file cap, truncation of the last chunk; numbered `[n]` for citations that are validated afterwards.
4. **Call-graph relationships** for the kept chunks (calls / called-by / extends).
5. **Conversation history** (`agent/memory.py`): last `HISTORY_TURNS` turns nearly verbatim, older turns one line each, under `HISTORY_TOKEN_BUDGET`; persisted per `conversation_id` in `data/conversations/`.
6. **Task-specific facts**: the analysis, the failing test output, reviewer feedback, and for the coder the **exact untruncated source** of the function to edit (edits are matched literally).
7. A **repo map** (folder counts + files the request names), not a file listing.

If a model rejects the prompt as too long, the prompt is rebuilt with half the budget and retried once. Every response reports `context: {kept, dropped, tokens, budget, by_source}`.

## 3. Agent workflow — `app/agent/`

```
understand ─► plan ─► research ─► analyze ─► code ─► test ─► review ─► document ─► respond
  Planner    Planner  Researcher  Debugger   Coder   Tester  Reviewer  Documenter
                         ▲  ▲        │ need_more      │ failed    │ rejected
                         │  └────────┘                ▼           ▼
                         └──── research_more ◄──── reflect ───► code (retry with feedback)
```

Compiled with LangGraph (`StateGraph`, conditional edges; `build_graph(rt).get_graph().draw_mermaid()` draws it). Without LangGraph the same nodes run in a plain loop (`engine="simple"`); both are tested.

| Specialist | Decides / does |
|---|---|
| **Planner** | `understand`: intent (explain / debug / change / tests / review / docs), entities, queries, complexity, follow-up detection. `plan`: which specialists run and whether a patch, tests, review or docs are needed. The plan is checked against what the endpoint allows (`/chat` can never patch) |
| **Code Researcher** | A function-calling loop: **the model chooses** among `search_code`, `find_symbol`, `read_file`, `grep`, `callers`, `callees`, `impact`, `get_dependencies`, `list_files`. Repeated calls are refused, `MAX_TOOL_CALLS` per round, bad arguments come back as error text so the model can recover. If the model finds nothing, the planned queries run as a safety net |
| **Debugger** | Root cause (bugs) or grounded explanation, with `[n]` citations; asks for more context with `need_more` + follow-up queries → back to research |
| **Coder** | Multi-file `edits` + `new_files`, validated against the files before acceptance (each `search` must match exactly once). Invalid → retried with the reason. Legacy single-edit replies are accepted |
| **Tester** | Baseline and after-patch runs in a throw-away copy |
| **Reflection** | After a failed test the model picks `retry_code`, `research_more` (with queries) or `stop` |
| **Reviewer** | Patch: deterministic checks first (a patch that doesn't parse, `eval`, hard-coded secrets is rejected without a model call), then a model review that can send the patch back once. Review mode: static checks over the project + model review of the most relevant files |
| **Documenter** | Architecture overview from extracted facts (routes, imports, dependencies), and change notes after a patch |

Safety rails: `MAX_AGENT_STEPS` research rounds, `MAX_FIX_ATTEMPTS` patch attempts, `MAX_AGENT_TOTAL_STEPS` node visits, `MAX_LLM_CALLS`. Planning, reflection and review degrade to heuristics if the model is down; analysis and coding failures end the run with `status: "error"` (HTTP 502).

All endpoints are modes of this one graph: `/chat`, `/debug`, `/generate-fix` (explain / debug), `/change`, `/generate-tests`, `/review`, `/architecture`. Response shapes are unchanged; new fields are `conversation_id`, `plan`, `context`, `usage`, `review`, `edits`, `new_files`, `tool_calls`, `retrieval_rounds`, `attempts`.

## 3b. Tools the model can choose (v11) — `app/agent/registry.py`, `extras.py`

The researcher and the coder are function-calling loops: the **model picks the tools**, after each result it decides whether another one would change its understanding, and it stops when it would not. Tools are role-restricted.

| Tool | What it does | Researcher | Coder |
|---|---|:-:|:-:|
| `search_code(query)` | hybrid semantic + keyword search over functions/classes/files | ✓ | ✓ |
| `find_symbol(name)` | exact definition lookup | ✓ | ✓ |
| `read_file(path, start, end)` | line range (≤160 lines; secrets files refused, secret values masked) | ✓ | ✓ |
| `grep(query, regex)` | exact text / regex across all files (error strings, config keys) | ✓ | ✓ |
| `get_callers(name)` / `get_callees(name)` | call graph both ways | ✓ | ✓ |
| `get_dependencies(path?)` | declared dependencies, or a file's imports / importers | ✓ | |
| `impact(path)` | files and tests that depend on a file | ✓ | |
| `list_files(prefix)` | files under a folder | ✓ | |
| `search_docs(query)` | BM25 over README / docs / markdown sections | ✓ | |
| `find_config(query)` | config lines about a topic in yaml/json/toml/ini/settings.py/.env.example; **secret values masked** | ✓ | |
| `inspect_project()` | languages, frameworks, entry points, config files, test and lint setup, git state | ✓ | |
| `git_status()` / `git_log(path, n)` / `git_diff(path, ref, staged)` | what changed and when (read-only, args validated, secrets masked) | ✓ | |
| `search_web(query)` | Brave or Tavily; only offered when a key is configured; queries scrubbed; results wrapped as **untrusted** text | ✓ | |
| `run_tests(target?, with_pending_patch?)` | the suite or one test, in a sandbox copy; failing frames become evidence; budgeted (`MAX_TEST_RUNS`) | ✓ | ✓ |
| `run_linter(paths?, with_pending_patch?)` | ruff / flake8 / eslint + syntax check; findings marked BLOCKING | ✓ | ✓ |
| `generate_patch(edits / new_files / delete_files / unified_diff)` | validate a change against the real files and keep it as the *pending* proposal. **Nothing is written** | | ✓ |
| `apply_patch(run_tests?)` | apply the pending patch to a **sandbox copy** and check syntax, new lint findings, optionally tests | | ✓ |

*Example — "why is authentication failing?":* the model typically calls `search_code("authentication token validation")`, `get_callers("authenticate_user")`, `find_config("auth token")`, perhaps `git_log("auth.py")`, `run_tests()` to reproduce, then analyses; if the analysis says context is missing it requests more (the `need_more` loop) and the researcher runs again with that gap stated.

Tool output is data, never instructions (the prompts say so; web results are fenced as untrusted). Every result is scrubbed of literal secrets; `.env`, `*.pem`, `id_rsa` and similar files are never read.

## 3c. Debugging — the headline feature

```
paste an exception / stack trace / log / screenshot / description
   └► understand: ErrorReport (errors.py)   exception type · message · file · line · function · failing source line ·
   │                                         variables involved · call stack · chained causes · HTTP status · related functions (callers)
   └► research : exact leads first (failing frames, named symbols) → REPRODUCE by running the tests → model-chosen tools
   └► analyze  : root cause, grounded in code with [n] citations (asks for more context if needed)
   └► code     : patch through generate_patch/apply_patch (+ a regression test for bugs)
   └► test     : baseline · regression test on the ORIGINAL code (must fail) · tests + lint with the patch (judge())
   └► reflect  : failed? retry the patch, or go back and gather more code
   └► review   : deterministic checks, then a model review that can send it back once
   └► respond  : the report below
```

* **Languages:** Python, JavaScript/TypeScript, Java/Kotlin, Go, Rust traces; `Caused by` / `During handling of…` chains; logs with an embedded trace; HTTP-status log lines; plain descriptions (then the failing test run supplies the trace).
* **Screenshots:** attach/paste up to 3 images (PNG/JPEG/WebP/GIF, ≤5 MB). A vision-capable model transcribes the error text, which then goes through the same pipeline. Images are never persisted. Models without vision (the offline mock) say so and the run continues on the text.
* **The final report** always has these sections: **Root Cause** (exception, location, variable, explanation) · **Affected Files** (each once, with its roles: failure point / root cause / call stack / caller / modified) · **Explanation** · **Proposed Fix** (exact diff) · **Tests Executed** (before, regression test, after, linter) · **Verification Result**.
* **An honest verdict** (`app/verify.py: judge`): *resolved* only if a test that failed before now passes (or a new regression test fails on the original code and passes with the fix) and nothing else broke; *partial*; *not resolved* (still failing, new failures, collection errors, new blocking lint errors); *not verified* when the suite was green before too — "tests pass" alone is not proof the reported problem is fixed, and the report says so.

## 3d. The patch system — `app/patchset.py`, `app/patches.py`

**Engine.** A patch is any mix of targeted `edits`, a real `unified_diff`, whole-file `rewrites`, `new_files` and `delete_files`, across up to 25 files.
* Edits must match exactly once; if the text isn't found, a whitespace-tolerant line match is tried and the replacement is **re-indented** to the file's style (flagged in the diff UI). A miss returns the *closest real text* so the next attempt can be right.
* Unified-diff hunks are located by their **context**, not by line numbers (models get those wrong); blank-context and wrong-count diffs are tolerated; renames and binary diffs are refused.
* Existing code is preserved: CRLF/LF, BOM, trailing-newline state and file mode are kept; a change that would leave a previously valid `.py/.json/.toml/.yaml` unparseable is rejected before it can be applied.
* Safety: no paths outside the project or inside `.git`, no symlinks, no binary/non-UTF-8/over-1 MB files, ≤5 deletions.
* Writes are **atomic and all-or-nothing** (temp file + rename, rollback on failure), with a stale check (sha256 of each file when the patch was built) and an undo record.

**Review and approval (API + Monaco).** Every agent patch (`/debug`, `/generate-fix`, `/change`, `/generate-tests`) is stored as a proposal and its `patch_id` returned; nothing is written. The IDE opens it in the **Monaco diff editor** using the server's exact before/after text, per-file approve/reject, with the agent's own verification shown. `POST /patches/{id}/apply` **requires `approved: true`** (403 otherwise) and may name a subset of files.

**After applying:** the repository is re-indexed, then tests and linter run automatically against the pre-apply baseline. Failing checks show the failing tests and blocking lint errors, and offer **Ask the agent to fix this** (`/patches/{id}/repair`): the agent analyses the failure against the current code and proposes a *new* proposal linked to the old one. **Revert** restores every file byte-for-byte (refusing, unless forced, if the files were edited since).

| Endpoint | |
|---|---|
| `POST /patches` | validate a hand-made patch (edits / unified diff / new / deleted files) → proposal |
| `GET /patches[?repo_id]`, `GET /patches/{id}`, `GET /patches/{id}/file?path=` | list, summary, exact original/modified text of one file |
| `POST /patches/{id}/apply` `{approved, files?, run_checks?}` | apply approved files + run checks (403 / 409 stale / 400) |
| `POST /patches/{id}/checks`, `/revert`, `/reject`, `/repair` | re-run checks, undo, discard, agent correction |

## 3e. Testing and code quality (v12) — `app/quality/`

* **Frameworks** (`frameworks.py`): pytest (also runs unittest-style tests), Jest, Vitest, Mocha, `npm test`, Go (`go test -json`), Cargo, Maven, Gradle: detected from the repo, run (whole suite or specific tests) through the sandbox, parsed into one result shape `{counts, failed_tests[], total}`. Polyglot repos run each framework.
* **Test generation** (`mode: tests` / `/generate-tests`): `test_patterns.py` reads how *this* repository tests (framework, layout, naming, fixtures, mocking, assertion style, a real sample, where the new file belongs) and the prompt carries it. The agent writes unit tests plus an integration-style test where several components interact, **runs them**, and judges the result:
  * a failing generated test goes to reflection, which decides **test wrong** (fix the test; implementation edits are refused) or **implementation wrong** (keep the test; the coder may now edit source). Such a patch is flagged *⚠ Implementation Changed* in the report and in the diff review.
  * the report shows the files written, conventions followed, tests executed before/after, **coverage of the file under test (before → after, uncovered lines)** and a verdict.
* **Analyzers** (`analyzers.py`): Ruff, Pylint, mypy, Bandit, Semgrep (offline rule pack), ESLint, pip-audit, npm audit, go vet, Clippy → one finding shape and severity scale (critical/high/medium/low/info). Tools that need a network (audits) are opt-in; missing tools are reported as *unavailable*, never as clean.
* **Coverage** (`coverage.py`): coverage.py JSON, Jest/Vitest json-summary, Go profiles, collected in the same run as the tests. Cargo/Maven/Gradle: reported unsupported.
* **Quality score** (`score.py`): 0-100 and A-F from tests (30), coverage (20), lint (15), types (10), security (20) and maintainability (5: function length and cyclomatic complexity from the AST). Unmeasured dimensions are left out and the rest re-weighted: a missing tool is neither a pass nor a fail. The formula is in the module docstring.
* **UI**: the *Code quality* tab (gauge icon in the activity bar): run with chosen tools, live progress, score by dimension, tests, per-file coverage bars (click opens the file), findings by category (click opens the line), most complex functions, notes about skipped/unavailable tools. API: `POST /quality/run` → `GET /quality/jobs/{id}`, `/quality/latest`, `/quality/history`, `/quality/analyzers`.

## 3f. Secure execution

Everything that runs repository code runs in a locked-down Docker container (no network, CPU/memory/pid limits, read-only root, tmpfs scratch, no capabilities, non-root, enforced timeout, bounded output, no host secrets), or **nothing runs**. Full description, the opt-in networked steps and the honest limits: [docs/SANDBOX.md](SANDBOX.md). `GET /sandbox/status`; the UI shows a green *Docker sandbox* badge or a red *Host execution (unsafe)* / *Sandbox unavailable* one.

## 3g. Git and GitHub

* **Git intelligence** (`git_intel.py`, tools `git_branches`, `git_show`, `git_blame`, `git_file_at`, `git_changed_files`, `git_authors`, `git_log` with author/since/grep/ref, `git_diff`): branches, commits, diffs, history, changed files, authors, blame, previous versions of any file. Read-only, validated refs and paths, hardened against hostile `.git/config` (see SANDBOX.md).
* **GitHub** (`github_api.py`): OAuth login and repository picker (existing), plus pull requests, issues, reviews. 
* **Workflows**

| Workflow | Endpoint | What happens |
|---|---|---|
| Analyze PR | `POST /github/pr/analyze` | summary, change type, risk and why, key changes, impact (call/import graph), test assessment, concerns, questions, suggested reviewers (from git history). Read-only |
| Review PR | `POST /github/pr/review` | a **draft** review: verdict + inline comments anchored to lines that really appear in the diff; Ruff/Bandit/Semgrep run on the PR head in the sandbox and only findings on *added* lines count; comments on lines outside the diff are folded into the summary; existing human comments are not repeated |
| Fix Issue | `POST /github/issue/fix` | the debugging agent works from the issue and returns a patch proposal |
| Create Branch | `POST /git/branch` | local only |
| Generate Commit | `POST /git/commit-message` then `POST /git/commit` | message drafted in the repo's own style; commits are selective and never include secret-looking files |
| Push Changes | `POST /actions/push` → approve | see below |
| Create Pull Request | `POST /git/pr-description` (draft) then `POST /actions/pull-request` → approve | |
| Post a review | `POST /actions/review` → approve | |

* **Human approval** (`actions.py`): pushing, force-pushing, opening a PR and posting a review are **two-step tickets**. *Propose* computes exactly what would happen (remote, branch, commits, files, the full text) and stores it; nothing leaves the machine. Only `POST /actions/{id}/approve {"approved": true}` executes, after checking that the world still matches the preview (branch tip, PR head SHA; 409 otherwise). Force pushes and pushes to the default branch also require typing the branch name. Pending actions expire after 30 minutes. **No agent tool can push, open a PR, post, commit, check out or approve** (a test asserts the registry has none). Discarding changes and forced checkouts now require `approved: true` server-side too.
* PR/issue text is third-party data: the prompts say so, and a hostile PR description can at most change the *draft* a human then reads.

## 4. Using it

```bash
LLM_PROVIDER=openai OPENAI_API_KEY=... LLM_MODEL=<model> LLM_MODEL_FAST=<cheaper model>   # or gemini + GEMINI_API_KEY
curl -X POST localhost:8000/debug -H 'content-type: application/json' \
  -d '{"repo_id":"<id>","question":"<error or stack trace>"}'                              # response has conversation_id
curl -X POST localhost:8000/chat  -H 'content-type: application/json' \
  -d '{"repo_id":"<id>","question":"and why does that happen?","conversation_id":"<id from above>"}'
curl localhost:8000/llm/usage                                                              # tokens, latency, retries per task/model
```

## 5. What is and is not verified
(v12: 378 → 461 offline tests, adding the sandbox (flags, timeout kill, output bound, fake Docker), framework parsers, analyzers against real Ruff/Pylint/mypy/Bandit/Semgrep, coverage, scoring, test generation, git hardening, GitHub client, approvals and the PR/issue workflows. v11 additions: 247 → 378 offline tests, including a full debugging run through the real OpenAI provider code with a fake HTTP client, the patch engine's edge cases, patch approval / stale / revert / repair over the API, verification verdicts, every tool, and the web-search request formats for Brave and Tavily.)

Tested (247 tests, offline): request construction and response parsing for both providers against fake SDK clients, retries / backoff / fallback / budget, JSON repair, usage accounting, every routing branch of the graph on both engines (reflection, research loops, review revision, degradation), stack-trace parsing, context budgeting and ranking, memory persistence, API fields.

**Not verified: real Gemini / OpenAI calls, real Brave / Tavily calls, a real Docker daemon (the sandbox is tested with a stand-in `docker` that checks the flags and the timeout/cleanup paths), real GitHub (tested against a fake GitHub that records every request), real Jest/Go/Cargo/Maven runs (their output parsers are tested on recorded output), and the new UI panels in a browser (they type-check and build)** (request/response shapes were checked against the providers' documentation and tested with a fake HTTP transport). No API key was available here. Not run in a browser by me: the Monaco review tab type-checks and builds (`next build`) but was not exercised interactively. Provider code follows each SDK's documented request/response shapes (checked against the installed SDK types), but run one real `/debug` before relying on it. Default model names (`gpt-4o-mini`, `gemini-2.0-flash`) may be outdated: set `LLM_MODEL`. Patch *quality* from a real model is unmeasured.
