# The strict review engine

`app/review/` is a deterministic reviewer: no language model, no sampling, no scores guessed from text. It answers one question precisely: *what in this code is certainly wrong, and where?* It reviews **every analysable file** of a project (about 130 files in under 2 seconds) and states what it covered and what it cannot see.

## How it works

```
iter_source_files(project copy)            every text file, minus dependency/build folders and minified bundles
        │
        ├── .py            pycheck.py     compile() → SyntaxError with line/column
        │                                 ast + scope analyser → names, attributes, imports, calls, patterns, security
        ├── .js .jsx .ts .tsx            treecheck.py   Tree-sitter parse → ERROR / MISSING nodes (precise location of the innermost error)
        │                                               pattern rules (assignment in condition, empty catch, debugger…)
        │                                 jscheck.py    import resolution, export check, package.json check, undefined identifiers / components / hooks
        ├── .java .go .rs .c .cpp        treecheck.py   syntax only
        └── .json .yaml .toml .html .css datacheck.py   strict parse / tag balance / bracket balance
        │
        ▼
findings: rule id, category, severity, confidence, file, line, column, message, code line + context, fix
+ coverage: per language, what was checked ("depth"), files skipped and why, and what static analysis cannot see
```

### Python (the deepest checker)
1. **Syntax:** `compile()`. Python's own message, line and column, plus a hint (`'(' was never closed`, `expected ':'`…).
2. **Names:** a real scope model (module, function, class, comprehension, lambda; `global`/`nonlocal`; walrus; `match`; comprehensions; closures). A name read but not bound anywhere visible, and not a built-in, is an error with a *did you mean* from the names in scope. Python 2 leftovers (`xrange`, `unicode`…) are called out. Code using `exec`, `locals()` or star imports is skipped rather than guessed.
3. **Attributes:** `self.x` read in a method but never assigned in the class (or its in-file bases). Only reported when every base class is known, so inherited attributes are never flagged.
4. **Standard library:** `os.pth` → *module `os` has no attribute `pth`; did you mean `path`?* (checked against the running Python; platform-only names are downgraded).
5. **Imports across your project:** `from services.eta import calculate_etaa` is an error when `services/eta.py` does not define it; so is a module that does not exist.
6. **Calls across your project:** wrong number of positional arguments, unknown or duplicated keyword arguments (with *did you mean*), missing required arguments, for functions, classes with `__init__`, and `self.method()` calls.
7. **Bug patterns and security:** see the catalogue below.

### JavaScript / TypeScript / React
Tree-sitter grammars give exact syntax errors (a missing or extra `}`, `)`, an unclosed JSX tag or expression). The reported position is the **innermost** error, not the start of the surrounding function. On top of that:
- `JS-IMPORT`: a relative import that resolves to no file (`'./Hedaer'`), with a *did you mean* from sibling files; assets (`./logo.svg`) resolve against the real file list.
- `JS-EXPORT`: importing a named or default export the target module does not have.
- `JS-PACKAGE`: a package not listed in `package.json` (typos like `reactt`), when `package.json` exists and no `node_modules` is present.
- `JS-UNDEFINED`: an identifier that is used but never declared or imported, in an ES module. Browser/Node globals are known. Capitalised JSX tags and `use*` hooks are reported with higher severity because rendering them throws.
- Pattern rules: assignment in a condition, `debugger`, empty `catch`, loose `==` (aggregated to one note per file), unreachable code, unused imports.

## Rule catalogue

| Rule | Severity | Meaning |
|---|---|---|
| `PY-SYNTAX` `JS-SYNTAX` `TS-SYNTAX` `JAVA-SYNTAX` `GO-SYNTAX` `RS-SYNTAX` `C-SYNTAX` `CPP-SYNTAX` | high | the file cannot be parsed |
| `JSON-SYNTAX` `YAML-SYNTAX` `TOML-SYNTAX` | high | invalid data file |
| `HTML-UNCLOSED` `HTML-STRAYCLOSE` `BRACE` | high | unclosed or stray tag / bracket in HTML, inline scripts, CSS |
| `PY-UNDEFINED` `JS-UNDEFINED` | high (medium for a plain unknown name in JS) | a name that does not exist |
| `PY-ATTR` `PY-MODATTR` | high | misspelled attribute of `self` or of a standard-library module |
| `PY-IMPORT` `JS-IMPORT` `JS-EXPORT` `JS-PACKAGE` | high (medium for an unlisted package with no close match) | importing something that does not exist |
| `PY-ARITY` `PY-NOSELF` | high | calling a function or method wrongly |
| `PY-DIVZERO` `PY-ASSERT` `PY-TYPEMIX` `PY-FORMAT` | high | will raise or never works |
| `PY-ISLIT` `PY-MUTDEF` `PY-REDEF` `PY-DUPKEY` `PY-BAREEXCEPT` `PY-SWALLOW` `PY-WARN` `JS-ASSIGNCOND` `JS-EMPTYCATCH` `JS-DEBUGGER` | medium (high for assignment in a condition) | bug risks |
| `PY-UNREACHABLE` `JS-UNREACHABLE` | low | code after `return` / `raise` / `break` |
| `PY-SQLI` `PY-SHELL` `PY-OSSYSTEM` `PY-YAML` `PY-TLS` `PY-DEBUG` `PY-EVAL` `PY-MKTEMP` `SECRET` | high / medium | security |
| `PY-PICKLE` `PY-WEAKHASH` | low | worth knowing; often fine |
| `PY-UNUSEDIMPORT` `PY-UNUSEDVAR` `JS-UNUSEDIMPORT` `PY-NONECMP` `JS-LOOSEEQ` | low | unused code and style notes (hidden by default in the UI) |

Each finding also carries a **confidence**. Rules that cannot be fully sure (for example `self.x` when only part of a class hierarchy is visible) say so.

## Guarding against false alarms
A reviewer that cries wolf gets ignored, so the engine is measured on working code as well as on broken code (`python -m app.review.bench --corpus app frontend/src`): the project's own 130-file Python backend yields no high-severity findings, and its 117-file React/TypeScript frontend yields none at high or medium. Building that check found and fixed real false positives (psycopg's safe `sql.SQL(...).format()`, JSX lower-case tags, nested functions mistaken for methods, raw `&` in JSX text, secrets mentioned in docstrings). Generated and minified files (`_next/`, `*.min.js`, very long lines) are skipped.

## What it deliberately does not do
- **Type checking.** `f("a")` where `f` expects an `int` is not found. The Code Quality scan runs `mypy` for Python when it is installed.
- **Logic errors.** Valid code that does the wrong thing (wrong formula, wrong comparison) is invisible to static rules. The AI review can look for these; its findings are marked as model output and checked against the real code (a finding that points at code which is not there is flagged).
- **Other languages in depth.** Java, Go, Rust, C and C++ get syntax checks only.
- **Dynamic code.** `exec`, `setattr`, star imports, bundler aliases and `<script>`-tag globals are skipped, never guessed.

## Using it
| Way | How |
|---|---|
| Web app | **Code Review** (second item in the sidebar), or the **Review code** button on the dashboard |
| Paste code | Code Review → *Paste code* (no project needed; checks that need other files are skipped) |
| API | `POST /repositories/{id}/review/static`, `POST /review/snippet`, `POST /repositories/{id}/review/export?fmt=markdown|sarif|json` |
| CLI / CI | `python -m app.review PATH [--fail-on high|medium|low|never] [--json|--sarif|--markdown]` (exit status 1 when the threshold is hit) |
| Agent | the chat's **Review** mode runs this engine over the whole project and adds AI findings on top |

## Benchmark
`python -m app.review.bench` runs 53 seeded mistakes and 5 clean programs; the committed result is [eval/results/review_benchmark.md](../eval/results/review_benchmark.md). The cases are in `app/review/bench.py` and double as the regression suite (`tests/test_review_bench.py`, `tests/test_v17_strict_review.py`).

## Adding a rule
1. Add the check to `pycheck.py` (Python), `jscheck.py`/`treecheck.py` (JS family) or `datacheck.py`.
2. Add a seeded case to `app/review/bench.py` and a clean case if the rule could misfire.
3. Run `python -m app.review.bench --corpus app frontend/src`: the new rule must find its case and add no high/medium findings to working code.
