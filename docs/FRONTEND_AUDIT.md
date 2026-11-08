# Audit: what looked real but wasn't, and what was done about it

Scope: the v15 web app and the backend endpoints it called. Every item below was checked in the code, not assumed.

| # | Finding | Why it was misleading | What changed |
|---|---|---|---|
| 1 | Test output was cut to the last **3,000 characters** (`sandbox.run_tests`) | Tracebacks were usually lost, so every failure looked like the same generic line | Output keeps up to 60,000 characters, plus separate stderr and the process **exit code** |
| 2 | pytest ran with `-q`, which prints dots, not test names | The UI could only say "N passed" with no per-test truth | Runs with `-v` and `-rfEsxX`; every test's real outcome, skip reasons and per-failure **traceback, call frames (file:line) and error lines** are parsed from pytest's own output |
| 3 | Test history lived only in the browser tab | "History" was a list of this session's clicks | Runs are **recorded on the server only when something executed** (`GET /repositories/{id}/test-runs`). Nothing is recorded for runs that never started |
| 4 | "Sandbox unavailable" / "no framework" came back in the same shape as a real result | A run that never started looked like a (generic) test result | The API now says `executed: false`; the Testing page shows **Not executed** with the reason and no counts |
| 5 | The Testing page had no notion of *discovered* vs *executed* tests | Discovered counts and executed counts were mixed together | New discovery endpoint (`GET /repositories/{id}/tests`): files, cases, framework, the exact command that would run, which modules each test file covers (verified by import vs inferred by name). The page shows discovered and executed **separately**, per-case "not run" where a run did not execute that test |
| 6 | The offline mock model's answers were rendered exactly like AI answers (chat, debug, review) | A list of retrieved files read as an analysis | An **Offline mock model** notice is shown on every such result. The dashboard and architecture explanations are **not generated at all** with the mock (the API answers `unavailable` with the reason) |
| 7 | Suggested prompts were fixed template sentences | They looked tailored but were identical for every repository | Suggestions come from the parser: this project's routes, most-called functions, models, external packages and untested modules, each with its basis. Generic ideas appear only when nothing project-specific exists, and are labelled "Generic ideas" |
| 8 | Dashboard was mostly counters and charts | Numbers without understanding | Dashboard now leads with AI project understanding (cited, cached per index version, or an honest "needs a model" with parser-detected facts), then structure, starting questions, risks, and agent activity |
| 9 | Architecture views drew modules/calls but never said how reliable each edge was | Name-matched call guesses looked the same as resolved imports | System graph marks every edge **verified** (resolved by the parser) or **inferred** (name match); the 3D and 2D views draw inferred edges dashed and can hide them |
| 10 | "Untested" style signals considered only direct test imports | A module exercised through another module counted as untested | Untested = **no test reaches it through imports at any depth and none is named after it** |

## v17 additions
| # | Finding | Fix |
|---|---|---|
| 11 | **Code review was not a real review.** Review mode examined only the first 40 `.py/.js/.ts` files and ran a handful of patterns (bare except, mutable default, `eval`, secrets). With no AI model nothing else ran, so typos, undefined names, wrong imports and syntax errors were invisible | New strict engine analyses every file with real parsers and rules (see PROGRESS.md v17). Agent review mode now uses it for the whole project |
| 12 | **Edits to your original folder were never seen.** "Re-index" re-indexed the server's old copy | Source-status check + "Sync & review again" / "Sync from source & re-index" |
| 13 | The page became unclickable after adding/removing a project | Non-modal menus + safety net |
| 14 | 3D labels were tiny and unreadable; the 3D view was the default | Readable System map / Execution flow / File structure are the default views; 3D labels are fixed-size |

## Still not real / not done
- The chat does not stream words; the backend streams events (phases, tool calls). Answers appear when complete.
- Test **coverage** is only measured by the quality scan (it is shown there, labelled with the scan time), not by plain test runs.
- Non-Python frameworks (Jest, Vitest, Go, Cargo, Maven, Gradle) keep their previous result detail: counts and failure messages, but no per-test list or file:line frames, because their parsers don't provide them.
- Data model **relationships** are not extracted by the parser, so none are drawn (models are listed with their file and field count).
- Execution flow is the call graph from a route handler: calls through dynamic dispatch, callbacks or framework hooks are invisible to static analysis.
- Nothing here was verified in a real browser by the author of this change (no browser was available): see PROGRESS.md.
