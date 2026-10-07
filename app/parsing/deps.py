from __future__ import annotations
import ast
import json
import re


def python_imports(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    mods: list[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods.append(n.module)
    return sorted(set(mods))


def parse_requirements(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            out.append(re.split(r"[<>=!~\[; ]", line)[0])
    return out


def parse_package_json(text: str) -> list[str]:
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        return []
    return sorted({*d.get("dependencies", {}), *d.get("devDependencies", {})})
