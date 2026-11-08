"""Export formats for a review result: Markdown (people), SARIF 2.1.0 (GitHub code scanning and other tools)."""
from __future__ import annotations

LEVEL = {"high": "error", "medium": "warning", "low": "note"}


def to_markdown(r: dict, name: str = "project") -> str:
    s = r["summary"]["by_severity"]
    L = [f"# Code review: {name}", "", f"- Files analysed: **{r['coverage']['files_analysed']}** in {r['duration_ms']} ms ({r['engine']})",
         f"- Findings: **{r['summary']['total']}** ({s.get('high', 0)} high, {s.get('medium', 0)} medium, {s.get('low', 0)} low)", ""]
    langs = ", ".join(f"{l['language']} ({l['files']})" for l in r["coverage"]["languages"])
    if langs:
        L += [f"Languages: {langs}", ""]
    cur = None
    for f in r["findings"]:
        if f["file"] != cur:
            cur = f["file"]; L += ["", f"## `{cur}`", ""]
        L.append(f"- **{f['severity'].upper()}** line {f['line']}, col {f['col'] + 1} `[{f['rule']}]` {f['message']}")
        if f.get("evidence"):
            L.append(f"  - code: `{f['evidence'].strip()[:160]}`")
        if f.get("fix"):
            L.append(f"  - fix: {f['fix']}")
    L += ["", "## What this review cannot see", ""] + [f"- {x}" for x in r["limits"]]
    return "\n".join(L) + "\n"


def to_sarif(r: dict, name: str = "project") -> dict:
    rules: dict[str, dict] = {}
    results = []
    for f in r["findings"]:
        rules.setdefault(f["rule"], {"id": f["rule"], "name": f["rule"], "shortDescription": {"text": f["category"]}, "defaultConfiguration": {"level": LEVEL.get(f["severity"], "warning")}})
        results.append({"ruleId": f["rule"], "level": LEVEL.get(f["severity"], "warning"), "message": {"text": f["message"] + (f" Fix: {f['fix']}" if f.get("fix") else "")},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": f["file"]}, "region": {"startLine": f["line"], "startColumn": f["col"] + 1}}}]})
    return {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "CodeScout AI strict review", "version": r["engine"], "rules": list(rules.values())}}, "results": results, "properties": {"project": name}}]}
