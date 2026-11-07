"""Test selection from changed files and the import graph: which tests could be affected by a change?

Deterministic (no model). A test file is selected when it is itself changed, when it imports (directly or through up to `depth` hops of
internal imports) a changed non-test file, or when its name follows the convention for a changed module (`test_<stem>.py`,
`<stem>.test.ts`, `<Stem>Test.java` ...). Returns None when the change cannot be mapped safely (config / conftest / build files changed,
or nothing matched): the caller then runs the whole suite."""
from __future__ import annotations
from .frameworks import is_test_path

_GLOBAL = ("conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "requirements.txt", "package.json", "tsconfig.json", "jest.config.js",
           "vitest.config.ts", "go.mod", "Cargo.toml", "pom.xml", "build.gradle")


def _stem(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.split(".", 1)[0].lower().replace("_", "").replace("-", "")


def select_tests(changed: list[str], tree: list[str], imported_by: dict[str, set[str]], depth: int = 3) -> list[str] | None:
    changed = [c for c in changed if c]
    if not changed or any(c.rsplit("/", 1)[-1] in _GLOBAL for c in changed):
        return None
    tests = {f for f in tree if is_test_path(f)}
    picked = {c for c in changed if c in tests}
    sources = [c for c in changed if c not in tests]
    seen, frontier = set(sources), set(sources)
    for _ in range(depth):          # who imports the changed code, and who imports those
        frontier = {p for f in frontier for p in imported_by.get(f, ()) if p not in seen}
        seen |= frontier
        if not frontier:
            break
    picked |= {f for f in seen if f in tests}
    stems = {_stem(s) for s in sources}
    for t in tests:
        ts = _stem(t).removeprefix("test").removesuffix("test").removesuffix("spec")
        if ts and ts in stems:
            picked.add(t)
    return sorted(picked) or None
