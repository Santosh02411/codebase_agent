"""Code coverage, collected while the tests run (one execution gives both results).
Python: pytest-cov (coverage.py JSON). Jest/Vitest: json-summary. Go: -coverprofile. Cargo / Maven / Gradle: not collected (needs extra tooling): reported as unsupported."""
from __future__ import annotations
import json
from pathlib import Path

from .frameworks import Framework, is_test_path

PY_FILE = ".agent-coverage.json"
JS_DIR = ".agent-coverage"
GO_FILE = ".agent-cover.out"


def supported(fw: Framework) -> bool:
    return fw.name in ("pytest", "jest", "vitest", "go")


def command(fw: Framework, base: list[str]) -> list[str]:
    """`base` (the framework's normal test command) extended to also collect coverage."""
    if fw.name == "pytest":
        return base + ["--cov=.", f"--cov-report=json:{PY_FILE}", "--cov-report="]
    if fw.name in ("jest", "vitest"):
        return base + ["--coverage", "--coverageReporters=json-summary", f"--coverageDirectory={JS_DIR}"]
    if fw.name == "go":
        return [c for c in base if c != "./..."] + [f"-coverprofile={GO_FILE}", "./..."]
    return base


def _ranges(lines: list[int]) -> list[str]:
    out, start, prev = [], None, None
    for n in sorted(lines):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if prev != start else str(start))
    return out


def _file(path: str, covered: int, total: int, missing: list[int] | None = None) -> dict:
    return {"path": path, "percent": round(100.0 * covered / total, 1) if total else 100.0, "covered": covered, "total": total, "missing": _ranges(missing or [])[:30]}


def collect(root: Path, fw: Framework) -> dict | None:
    """Parse the coverage artefact the test run left in `root` (a throw-away copy). None if there is none."""
    try:
        if fw.name == "pytest":
            d = json.loads((root / PY_FILE).read_text())
            files = [_file(p, v["summary"]["covered_lines"], v["summary"]["num_statements"], v.get("missing_lines")) for p, v in d.get("files", {}).items() if not is_test_path(p)]
            total = sum(f["total"] for f in files)
            cov = sum(f["covered"] for f in files)
            return {"tool": "coverage.py", "percent": round(100.0 * cov / total, 1) if total else 0.0, "covered": cov, "total": total, "files": sorted(files, key=lambda f: f["percent"])}
        if fw.name in ("jest", "vitest"):
            d = json.loads((root / JS_DIR / "coverage-summary.json").read_text())
            files = []
            for p, v in d.items():
                if p == "total":
                    continue
                rel = p.split("/work/", 1)[-1] if "/work/" in p else p.replace(str(root) + "/", "")
                if not is_test_path(rel):
                    files.append(_file(rel, v["lines"]["covered"], v["lines"]["total"]))
            total = sum(f["total"] for f in files)
            cov = sum(f["covered"] for f in files)
            return {"tool": fw.name + " (istanbul/v8)", "percent": round(100.0 * cov / total, 1) if total else 0.0, "covered": cov, "total": total, "files": sorted(files, key=lambda f: f["percent"])}
        if fw.name == "go":
            return parse_go_profile((root / GO_FILE).read_text())
    except (OSError, ValueError, KeyError):
        return None
    return None


def parse_go_profile(text: str) -> dict:
    per: dict[str, dict] = {}
    for line in text.splitlines()[1:]:
        try:
            loc, n_stmt, count = line.rsplit(" ", 2)
            path, rng = loc.rsplit(":", 1)
            start, end = (x.split(".")[0] for x in rng.split(","))
        except ValueError:
            continue
        f = per.setdefault(path, {"covered": 0, "total": 0, "missing": []})
        f["total"] += int(n_stmt)
        if int(count) > 0:
            f["covered"] += int(n_stmt)
        else:
            f["missing"] += list(range(int(start), int(end) + 1))
    files = [_file(p.split("/", 3)[-1] if p.count("/") > 2 else p, v["covered"], v["total"], v["missing"]) for p, v in per.items() if not p.endswith("_test.go")]
    total = sum(f["total"] for f in files)
    cov = sum(f["covered"] for f in files)
    return {"tool": "go test -cover", "percent": round(100.0 * cov / total, 1) if total else 0.0, "covered": cov, "total": total, "files": sorted(files, key=lambda f: f["percent"])}
