"""Learn how THIS repository writes tests, so generated tests look like they belong: framework, naming, where files live, fixtures,
mocking and assertion style, and a real example to imitate. Deterministic: it only reads files."""
from __future__ import annotations
import os
import re
from pathlib import Path

from . import frameworks
from .frameworks import Framework, is_test_path

MOCK_HINTS = {"unittest.mock": "unittest.mock", "from unittest import mock": "unittest.mock", "mock.patch": "unittest.mock", "mocker": "pytest-mock (the `mocker` fixture)", "monkeypatch": "pytest monkeypatch", "jest.mock": "jest.mock", "vi.mock": "vi.mock",
              "sinon": "sinon", "testify/mock": "testify/mock", "gomock": "gomock", "mockito": "Mockito", "mockall": "mockall", "unittest.TestCase": "unittest.TestCase"}


def _read(root: Path, rel: str, limit: int = 20_000) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _ext(path: str) -> str:
    return os.path.splitext(path)[1]


def _module_name(target: str) -> str:
    return os.path.splitext(os.path.basename(target))[0]


def suggest_path(fw: Framework, target: str, tests: list[str], root: Path) -> str:
    """Where a new test file for `target` belongs, following the repository's existing layout."""
    base, ext, stem = os.path.dirname(target), _ext(target), _module_name(target)
    if fw.name == "pytest":
        ends = sum(t.endswith("_test.py") for t in tests)
        starts = sum(os.path.basename(t).startswith("test_") for t in tests)
        name = f"{stem}_test.py" if ends > starts else f"test_{stem}.py"
        tdir = next((t.split("/")[0] for t in tests if t.split("/")[0] in ("tests", "test")), "")
        if tdir:
            mirrored = any(re.match(rf"{tdir}/{re.escape(base.split('/')[0])}/", t) for t in tests) if base else False
            return f"{tdir}/{base}/{name}" if mirrored and base else f"{tdir}/{name}"
        return f"{base + '/' if base else ''}{name}"
    if fw.name in ("jest", "vitest", "mocha", "npm"):
        spec = sum(".spec." in t for t in tests) > sum(".test." in t for t in tests)
        name = f"{stem}.{'spec' if spec else 'test'}{ext or '.js'}"
        if any("__tests__/" in t for t in tests) and not any(t.startswith(base + "/") and "__tests__" not in t for t in tests if base):
            return f"{base + '/' if base else ''}__tests__/{name}"
        return f"{base + '/' if base else ''}{name}"
    if fw.name == "go":
        return f"{base + '/' if base else ''}{stem}_test.go"
    if fw.name == "cargo":
        return f"tests/{stem}_test.rs"
    if fw.name in ("maven", "gradle"):
        m = re.match(r"(.*?)src/main/java/(.*)/(\w+)\.java$", target)
        return f"{m.group(1)}src/test/java/{m.group(2)}/{m.group(3)}Test.java" if m else f"src/test/java/{stem}Test.java"
    return f"tests/test_{stem}{ext}"


def analyze(root: Path, tree: list[str], target: str = "", fw: Framework | None = None) -> dict:
    fw = fw or frameworks.detect(root)
    tests = [f for f in tree if is_test_path(f) and f.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".mjs"))]
    out = {"framework": fw.name if fw else "unknown", "language": fw.language if fw else "", "test_files": len(tests), "test_dirs": sorted({t.rsplit("/", 1)[0] if "/" in t else "." for t in tests})[:8],
           "layout": "", "fixtures": False, "parametrized": False, "async_tests": False, "mocking": [], "assertions": "", "conftest": "", "sample_path": "", "sample": "",
           "suggested_path": "", "imports": ""}
    if fw is None:
        return out
    stem = _module_name(target) if target else ""
    # a representative example: a test for the same module, else one in the same folder, else a mid-sized one
    def score(t: str) -> tuple:
        return (stem != "" and stem in t, bool(target) and os.path.dirname(t) == os.path.dirname(target), -abs(len(_read(root, t, 5000)) - 1500))
    ranked = sorted(tests, key=score, reverse=True)
    corpus = ""
    for t in ranked[:12]:
        corpus += "\n" + _read(root, t, 8000)
    if ranked:
        out["sample_path"] = ranked[0]
        out["sample"] = "\n".join(_read(root, ranked[0], 6000).splitlines()[:70])
    low = corpus
    out["fixtures"] = "@pytest.fixture" in low or "beforeEach" in low or "setUp" in low or "@Before" in low
    out["parametrized"] = "parametrize" in low or "test.each" in low or "it.each" in low or "@ParameterizedTest" in low or "t.Run(" in low
    out["async_tests"] = "async def test_" in low or "async () =>" in low or "pytest.mark.asyncio" in low
    out["mocking"] = sorted({v for k, v in MOCK_HINTS.items() if k in low})
    out["assertions"] = ("pytest `assert` statements" if re.search(r"^\s*assert ", low, re.M) and "self.assert" not in low else "unittest `self.assert*` methods" if "self.assert" in low else
                         "`expect(...)` matchers" if "expect(" in low else "testify `assert/require`" if "testify" in low else "`t.Errorf` / `t.Fatalf`" if "t.Errorf" in low or "t.Fatalf" in low else
                         "`assert!` / `assert_eq!` macros" if "assert_eq!" in low else "JUnit `assert*`" if "assertEquals" in low or "assertThat" in low else "")
    if (root / "conftest.py").is_file():
        out["conftest"] = "\n".join(_read(root, "conftest.py", 2000).splitlines()[:30])
    imp = re.findall(r"^(?:from [\w.]+ import [\w, *]+|import [\w.]+(?: as \w+)?|const .*require\(.*\)|import .* from ['\"].*['\"];?)$", corpus, re.M)
    out["imports"] = "\n".join(list(dict.fromkeys(imp))[:8])
    out["layout"] = ("tests live in a separate top-level folder" if any(t.startswith(("tests/", "test/")) for t in tests) else "tests sit next to the code" if tests else "no existing tests to learn from")
    if target:
        out["suggested_path"] = suggest_path(fw, target, tests, root)
    return out


def render(p: dict) -> str:
    """The patterns as prompt text."""
    if not p.get("framework") or p["framework"] == "unknown":
        return "No test framework was detected; use the standard one for the language and keep tests simple."
    lines = [f"Test framework: {p['framework']} ({p['test_files']} existing test file(s); {p['layout']})."]
    if p.get("suggested_path"):
        lines.append(f"Put the new test file at: {p['suggested_path']}")
    if p.get("assertions"):
        lines.append(f"Assertion style: {p['assertions']}.")
    feats = [x for x, on in (("fixtures/setup", p["fixtures"]), ("parametrised cases", p["parametrized"]), ("async tests", p["async_tests"])) if on]
    if feats:
        lines.append("The existing tests use: " + ", ".join(feats) + ".")
    if p.get("mocking"):
        lines.append("Mocking: " + ", ".join(p["mocking"]) + ".")
    if p.get("imports"):
        lines.append("Typical imports in existing tests:\n" + p["imports"])
    if p.get("conftest"):
        lines.append("conftest.py (shared fixtures):\n" + p["conftest"])
    if p.get("sample"):
        lines.append(f"An existing test to imitate ({p['sample_path']}):\n```\n{p['sample']}\n```")
    return "\n".join(lines)
