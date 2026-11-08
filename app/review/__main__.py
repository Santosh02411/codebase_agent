"""Command line review: `python -m app.review PATH [--json] [--sarif] [--fail-on high|medium|low|never]`

Exit status 1 when a finding at or above --fail-on exists (default: high), so it can gate a commit or a CI job."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .engine import review_project
from .report import to_markdown, to_sarif


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.review", description="Strict static code review of a project folder (no AI model needed).")
    ap.add_argument("path", nargs="?", default=".", help="project folder (default: current directory)")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument("--sarif", action="store_true", help="print SARIF 2.1.0 (GitHub code scanning)")
    ap.add_argument("--markdown", action="store_true", help="print a Markdown report")
    ap.add_argument("--fail-on", default="high", choices=["high", "medium", "low", "never"], help="exit with status 1 when a finding of at least this severity exists")
    a = ap.parse_args(argv)
    root = Path(a.path).resolve()
    if not root.is_dir():
        print(f"not a folder: {root}", file=sys.stderr)
        return 2
    res = review_project(root)
    if a.json:
        print(json.dumps(res, indent=2))
    elif a.sarif:
        print(json.dumps(to_sarif(res, root.name), indent=2))
    elif a.markdown:
        print(to_markdown(res, root.name))
    else:
        s = res["summary"]["by_severity"]
        print(f"Reviewed {res['coverage']['files_analysed']} files in {res['duration_ms']} ms: {s.get('high', 0)} high, {s.get('medium', 0)} medium, {s.get('low', 0)} low")
        for f in res["findings"]:
            if f["severity"] == "low" and a.fail_on != "low":
                continue
            print(f"{f['file']}:{f['line']}:{f['col'] + 1}: {f['severity']} [{f['rule']}] {f['message']}")
    order = {"high": 0, "medium": 1, "low": 2}
    if a.fail_on != "never" and any(order[f["severity"]] <= order[a.fail_on] for f in res["findings"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
