"""Repository statistics shown on the dashboard."""
from __future__ import annotations
from collections import Counter, defaultdict

from .model import CODE_LANGS, VALUE_KINDS


def repo_stats(index) -> dict:
    facts, graph = index.facts, index.graph
    langs: dict[str, dict] = defaultdict(lambda: {"language": "", "files": 0, "lines": 0, "symbols": 0})
    kinds: Counter = Counter()
    parsers: Counter = Counter()
    for f in facts.values():
        row = langs[f.language]
        row["language"] = f.language
        row["files"] += 1
        row["lines"] += f.lines
        row["symbols"] += sum(1 for s in f.symbols if s.kind not in VALUE_KINDS)
        parsers[f.parser or "none"] += 1
        kinds.update(s.kind for s in f.symbols)
    languages = sorted(langs.values(), key=lambda r: (-r["lines"], r["language"]))
    code_files = [f for f in facts.values() if f.language in CODE_LANGS]

    apis = [{"method": a.method, "path": a.path, "handler": a.handler, "file": f.path, "line": a.line, "framework": a.framework}
            for f in facts.values() for a in f.apis]
    apis.sort(key=lambda a: (a["path"], a["method"]))
    models = [{"name": s.name, "file": s.file, "line": s.start, "framework": s.extra.get("framework", ""), "fields": len(s.extra.get("fields", []))}
              for f in facts.values() for s in f.symbols if "model" in s.tags]
    test_files = sorted(f.path for f in facts.values() if f.is_test or f.tests)
    ext_imports: Counter = Counter()
    for imports in graph.external.values():
        ext_imports.update(imports)

    declared = []
    for eco, names in index.deps.items():
        if isinstance(names, list) and eco in ("python", "node", "go", "rust", "java"):
            declared += [{"name": n, "ecosystem": eco} for n in names]
    errors = [{"file": f.path, "errors": f.errors} for f in facts.values() if f.errors][:20]
    total_calls = max(graph.call_total, 1)
    return {
        "files": len(index.tree), "code_files": len(code_files), "lines": sum(f.lines for f in facts.values()),
        "comment_lines": sum(f.comment_lines for f in facts.values()), "todos": sum(len(f.todos) for f in facts.values()),
        "languages": languages,
        "symbols": {
            "functions": kinds["function"], "methods": kinds["method"], "classes": kinds["class"], "interfaces": kinds["interface"] + kinds["trait"],
            "structs": kinds["struct"], "enums": kinds["enum"], "types": kinds["type"],
            "variables": kinds["variable"] + kinds["constant"] + kinds["macro"],
            "total": sum(v for k, v in kinds.items() if k not in VALUE_KINDS),
        },
        "dependencies": {"declared": declared, "declared_count": len(declared),
                         "external_imports": [{"name": n, "files": c} for n, c in ext_imports.most_common(60)],
                         "manifests": sorted(index.deps.get("files", []))},
        "tests": {"files": len(test_files), "cases": sum(len(f.tests) for f in facts.values()), "file_list": test_files[:30]},
        "apis": {"count": len(apis), "items": apis[:300]},
        "models": models[:200],
        "graph": {"module_edges": len(graph.module_edges), "files_with_imports": len(graph.imports_of),
                  "call_edges": sum(len(v) for v in graph.call_edges.values()), "calls_seen": graph.call_total,
                  "call_resolution_pct": round(100 * graph.call_resolved / total_calls, 1),
                  "inheritance_edges": sum(len(v) for v in graph.base_ids.values())},
        "parsers": dict(parsers), "parse_errors": errors,
    }
