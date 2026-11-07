"""The whole repository as one explorable graph, built ONLY from what the parser and resolver actually found.

Every edge says how it was established:
  import   resolved import between two files of this repository                       verified
  call     call resolved through imports / local scope / self                         verified
           call that matched several candidates by name only ("ambiguous")             inferred
  inherit  base class resolved to a class in this repository                           verified
  test     test file imports a module                                                  verified
           test file whose NAME matches a module and that has no import link to it     inferred
Nothing is invented: when the parser could not resolve something, the relationship is absent or marked inferred.
`insights()` summarises the same data (entry points, hubs, key modules, external dependencies, untested modules) without any model call."""
from __future__ import annotations
import posixpath
import re
import sys
from collections import defaultdict

VERIFIED_CALL = {"import", "local", "self"}
ENTRY_NAMES = {"main", "app", "index", "server", "manage", "cli", "wsgi", "asgi", "__main__", "run", "start"}
SYMBOL_KINDS = {"function", "method", "class", "interface", "struct", "enum", "trait"}


def _folder(path: str) -> str:
    return posixpath.dirname(path)


def _stem(path: str) -> str:
    return posixpath.basename(path).split(".")[0]


def _test_stem(path: str) -> str:
    s = _stem(path).lower()
    for p in ("test_", "tests_"):
        if s.startswith(p):
            s = s[len(p):]
    for q in ("_test", "_tests", ".test", ".spec"):
        if s.endswith(q):
            s = s[: -len(q)]
    return s


def system_graph(graph, max_files: int = 700, max_symbols: int = 900) -> dict:
    facts = graph.facts
    degree: dict[str, int] = defaultdict(int)
    for e in graph.module_edges:
        degree[e.src] += 1
        degree[e.dst] += 1
    all_files = sorted(facts)
    files = sorted(all_files, key=lambda p: (-degree[p], p))[:max_files] if len(all_files) > max_files else all_files
    keep = set(files)

    callers_n: dict[str, int] = defaultdict(int)
    callees_n: dict[str, int] = defaultdict(int)
    for sid, tg in graph.call_edges.items():
        callees_n[sid] += len(tg)
        for t in tg:
            callers_n[t] += 1

    folder_files: dict[str, int] = defaultdict(int)
    nodes_files = []
    for p in files:
        f = facts[p]
        for d in _ancestors(p):
            folder_files[d] += 1
        routes = [{"method": a.method, "path": a.path, "handler": a.handler, "line": a.line} for a in f.apis]
        entry = "route" if routes else ("name" if _stem(p).lower() in ENTRY_NAMES and not f.is_test and f.symbols else None)
        nodes_files.append({"id": p, "name": posixpath.basename(p), "folder": _folder(p), "language": f.language, "lines": f.lines, "symbols": len(f.symbols),
                            "is_test": bool(f.is_test), "tests": len(f.tests), "routes": routes, "entry": entry, "imports": len(graph.imports_of.get(p, ())),
                            "imported_by": len(graph.imported_by.get(p, ())), "external": sorted(graph.external.get(p, ()))[:12]})
    folders = [{"id": d, "name": posixpath.basename(d) or d, "parent": _folder(d), "files": n, "depth": d.count("/")} for d, n in sorted(folder_files.items())]

    cand = []
    for p in files:
        for s in facts[p].symbols:
            if s.kind in SYMBOL_KINDS:
                cand.append((p, s))
    cand.sort(key=lambda x: (not x[1].route, -(callers_n[x[1].id] + callees_n[x[1].id]), x[1].kind not in ("class", "interface", "struct"), x[0], x[1].start))
    per_file: dict[str, int] = defaultdict(int)
    symbols = []
    for p, s in cand:
        if len(symbols) >= max_symbols or per_file[p] >= 25:
            continue
        per_file[p] += 1
        symbols.append({"id": s.id, "file": p, "name": s.name, "qualname": s.qualname, "kind": s.kind, "start": s.start, "end": s.end, "route": s.route,
                        "callers": callers_n[s.id], "callees": callees_n[s.id], "parent": s.parent})
    sym_ids = {s["id"] for s in symbols}

    edges: list[dict] = []
    linked_tests: set[tuple[str, str]] = set()
    for e in graph.module_edges:
        if e.src not in keep or e.dst not in keep or e.src == e.dst:
            continue
        if facts[e.src].is_test and not facts[e.dst].is_test:
            edges.append({"source": e.src, "target": e.dst, "type": "test", "verified": True, "basis": "test file imports this module", "weight": max(1, len(e.names)), "label": ", ".join(e.names[:3])})
            linked_tests.add((e.src, e.dst))
        else:
            edges.append({"source": e.src, "target": e.dst, "type": "import", "verified": True, "basis": "resolved import", "weight": max(1, len(e.names)), "label": ", ".join(e.names[:3]) + ("…" if len(e.names) > 3 else "")})
    # tests that are linked only by name
    sources_by_stem: dict[str, list[str]] = defaultdict(list)
    for p in files:
        if not facts[p].is_test and facts[p].symbols:
            sources_by_stem[_stem(p).lower()].append(p)
    tested = {dst for _, dst in linked_tests}
    for p in files:
        if facts[p].is_test:
            for src in sources_by_stem.get(_test_stem(p), []):
                if (p, src) not in linked_tests:
                    edges.append({"source": p, "target": src, "type": "test", "verified": False, "basis": "file name matches (no import found)", "weight": 1})
                    tested.add(src)
    file_calls: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    call_names: dict[tuple[str, str], list[str]] = defaultdict(list)
    for sid, tg in graph.call_edges.items():
        a = graph.symbols.get(sid)
        for t, conf in tg.items():
            b = graph.symbols.get(t)
            if not a or not b:
                continue
            ok = conf in VERIFIED_CALL
            if a.file != b.file and a.file in keep and b.file in keep:
                fc = file_calls[(a.file, b.file)]
                fc[0] += 1
                fc[1] += int(ok)
                if b.name not in call_names[(a.file, b.file)]:
                    call_names[(a.file, b.file)].append(b.name)
            if sid in sym_ids and t in sym_ids:
                edges.append({"source": sid, "target": t, "type": "call", "verified": ok, "basis": f"call resolved via {conf}" if ok else "name matched several candidates", "weight": 1})
        for b in graph.base_ids.get(sid, []):
            if sid in sym_ids and b in sym_ids:
                edges.append({"source": sid, "target": b, "type": "inherit", "verified": True, "basis": "base class resolved", "weight": 1})
    for (a, b), (n, v) in file_calls.items():
        edges.append({"source": a, "target": b, "type": "file_call", "verified": v > 0, "basis": f"{n} call(s), {v} resolved", "weight": n, "label": ", ".join(call_names[(a, b)][:3]) + ("…" if len(call_names[(a, b)]) > 3 else "") })

    return {"folders": folders, "files": nodes_files, "symbols": symbols, "edges": edges,
            "stats": {"files": len(files), "symbols": len(symbols), "edges": len(edges), "tested_modules": len(tested),
                      "verified_edges": sum(1 for e in edges if e["verified"]), "inferred_edges": sum(1 for e in edges if not e["verified"])},
            "truncated": {"files": len(all_files) - len(files), "symbols": len(cand) - len(symbols)},
            "legend": {"verified": "established by the parser/resolver", "inferred": "a guess (name match); shown dashed"}}


def _ancestors(path: str):
    d = _folder(path)
    while d:
        yield d
        d = _folder(d)


def insights(graph, stats: dict) -> dict:
    """Deterministic facts about the project (no model): where it starts, what it is built around, what it depends on, what is untested."""
    facts = graph.facts
    sg = system_graph(graph)
    files = {f["id"]: f for f in sg["files"]}
    entry = [{"file": f["id"], "reason": "defines API routes" if f["entry"] == "route" else "conventional entry-point name", "detail": ", ".join(f"{r['method']} {r['path']}" for r in f["routes"][:4])} for f in files.values() if f["entry"]]
    entry.sort(key=lambda e: (e["reason"] != "defines API routes", e["file"]))
    tops: dict[str, dict] = {}
    for f in files.values():
        top = f["id"].split("/")[0] if "/" in f["id"] else "(root)"
        t = tops.setdefault(top, {"path": top, "files": 0, "symbols": 0, "test_files": 0, "languages": defaultdict(int)})
        t["files"] += 1; t["symbols"] += f["symbols"]; t["test_files"] += int(f["is_test"]); t["languages"][f["language"] or "other"] += 1
    folders = sorted(({**t, "languages": dict(t["languages"])} for t in tops.values()), key=lambda x: -x["files"])
    key_modules = sorted((f for f in files.values() if not f["is_test"] and f["imported_by"] > 0), key=lambda f: -f["imported_by"])[:8]
    key_modules = [{"file": f["id"], "imported_by": f["imported_by"], "symbols": [s["qualname"] for s in sg["symbols"] if s["file"] == f["id"]][:4]} for f in key_modules]
    hubs = sorted((s for s in sg["symbols"] if s["callers"] > 0 and not files.get(s["file"], {}).get("is_test")), key=lambda s: -(s["callers"]))[:8]
    hubs = [{"qualname": s["qualname"], "file": s["file"], "line": s["start"], "callers": s["callers"], "callees": s["callees"], "id": s["id"]} for s in hubs]
    ext: dict[str, int] = defaultdict(int)
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
    for p, names in graph.external.items():
        if p in files and not files[p]["is_test"]:
            for n in names:
                if p.endswith(".py") and n.split(".")[0] in stdlib:     # the standard library is not an "external package"
                    continue
                ext[n] += 1
    external = [{"name": n, "files": c} for n, c in sorted(ext.items(), key=lambda x: -x[1])[:14]]
    # "untested" = no test file reaches the module through imports (any depth) and none is named after it
    untested = [f["id"] for f in sorted(files.values(), key=lambda f: -f["symbols"]) if not f["is_test"] and f["symbols"] >= 1 and not graph.impact(f["id"])["tests"]][:12]
    long_fns = sorted(((s["end"] - s["start"], s) for s in sg["symbols"] if s["kind"] in ("function", "method")), key=lambda x: -x[0])[:5]
    risks = {"untested_modules": untested, "long_functions": [{"qualname": s["qualname"], "file": s["file"], "line": s["start"], "lines": n} for n, s in long_fns if n >= 60],
             "parse_errors": [e["file"] for e in stats.get("parse_errors", [])][:8], "todos": stats.get("todos", 0)}
    questions: list[dict] = []
    routes = stats.get("apis", {}).get("items", [])
    for r in routes[:2]:
        questions.append({"question": f"How does {r['method']} {r['path']} work, from the route to the data it touches?", "mode": "chat", "basis": f"route in {r['file']}:{r['line']}"})
    for h in hubs[:2]:
        questions.append({"question": f"What does `{h['qualname']}` do, and what depends on it?", "mode": "chat", "basis": f"called from {h['callers']} places"})
    for m in stats.get("models", [])[:1]:
        questions.append({"question": f"Explain the {m['name']} model and where it is created and used.", "mode": "chat", "basis": f"{m['framework']} model in {m['file']}"})
    if external:
        questions.append({"question": f"How is `{external[0]['name']}` used in this project?", "mode": "chat", "basis": f"imported in {external[0]['files']} files"})
    if untested:
        questions.append({"question": f"Review `{untested[0]}` for bugs. Nothing tests it.", "mode": "review", "basis": "no test reaches it through imports and none is named after it"})
    if entry and not routes:
        questions.append({"question": f"Walk me through what happens when `{entry[0]['file']}` runs.", "mode": "chat", "basis": entry[0]["reason"]})
    return {"entry_points": entry[:8], "routes": routes[:40], "models": stats.get("models", [])[:20], "folders": folders[:12], "key_modules": key_modules, "hubs": hubs,
            "external": external, "risks": risks, "suggested_questions": questions[:7], "graph": sg["stats"],
            "languages": [{"language": l["language"], "files": l["files"], "lines": l["lines"]} for l in stats.get("languages", [])[:6]]}


def facts_digest(ins: dict, repo_name: str = "") -> str:
    """The detected facts as text for a model prompt (small, and every line is something the parser found)."""
    L = [f"Project: {repo_name}" if repo_name else "Project facts"]
    if ins["languages"]:
        L.append("Languages: " + ", ".join(f"{l['language']} ({l['files']} files)" for l in ins["languages"]))
    if ins["entry_points"]:
        L.append("Entry points: " + "; ".join(f"{e['file']} ({e['reason']})" for e in ins["entry_points"][:6]))
    if ins["routes"]:
        L.append("API routes: " + "; ".join(f"{r['method']} {r['path']} -> {r['handler']} ({r['file']}:{r['line']})" for r in ins["routes"][:15]))
    if ins["models"]:
        L.append("Data models: " + "; ".join(f"{m['name']} ({m['framework']}, {m['file']})" for m in ins["models"][:10]))
    if ins["folders"]:
        L.append("Top-level folders: " + "; ".join(f"{f['path']}/ ({f['files']} files, {', '.join(f['languages'])})" for f in ins["folders"][:8]))
    if ins["key_modules"]:
        L.append("Most-imported modules: " + "; ".join(f"{m['file']} (imported by {m['imported_by']})" for m in ins["key_modules"][:6]))
    if ins["hubs"]:
        L.append("Most-called functions: " + "; ".join(f"{h['qualname']} in {h['file']} ({h['callers']} callers)" for h in ins["hubs"][:6]))
    if ins["external"]:
        L.append("External packages used: " + ", ".join(e["name"] for e in ins["external"][:12]))
    return "\n".join(L)


_NOISE = {"print", "len", "range", "str", "int", "float", "bool", "list", "dict", "set", "tuple", "isinstance", "super", "sorted", "enumerate", "zip", "min", "max", "sum", "any", "all", "open", "getattr", "setattr",
          "hasattr", "type", "repr", "map", "filter", "abs", "round", "reversed", "format", "join", "append", "get", "items", "keys", "values", "split", "strip", "lower", "upper", "startswith", "endswith"}


def flow(graph, sid: str, depth: int = 3, max_steps: int = 60, root=None) -> dict | None:
    """The calls a function makes, in the order they appear in its source, followed into the functions of this repository (depth-limited).
    Resolved steps come from the parser's call resolution; unresolved ones (library calls, dynamic dispatch) are listed as such, never invented."""
    root_path = root
    root = graph.symbols.get(sid)
    if not root:
        return None
    jsx_cache: dict[str, list[str]] = {}

    def lines_of(file: str) -> list[str]:
        if file not in jsx_cache:
            try:
                jsx_cache[file] = (root_path / file).read_text("utf-8", "replace").splitlines() if root_path is not None else []
            except OSError:
                jsx_cache[file] = []
        return jsx_cache[file]

    steps: list[dict] = []
    seen: set[str] = set()
    truncated = False

    def visit(sym, level: int) -> None:
        nonlocal truncated
        if sym.id in seen:
            return
        seen.add(sym.id)
        edges = graph.call_edges.get(sym.id, {})
        by_name: dict[str, list[tuple[str, str]]] = {}
        for t, conf in edges.items():
            tsym = graph.symbols.get(t)
            if tsym:
                by_name.setdefault(tsym.name, []).append((t, conf))
        unresolved = 0
        for c in sym.calls:
            if len(steps) >= max_steps:
                truncated = True
                return
            name = c.split(".")[-1]
            hit = by_name.get(name)
            if hit:
                t, conf = sorted(hit, key=lambda x: x[1] not in ("import", "local", "self"))[0]
                ts = graph.symbols[t]
                steps.append({"depth": level, "from": sym.qualname, "from_file": sym.file, "to": ts.qualname, "to_file": ts.file, "to_line": ts.start, "resolved": True, "verified": conf in VERIFIED_CALL, "label": f"{name}()", "id": ts.id, "kind": "call"})
                if level < depth:
                    visit(ts, level + 1)
            elif name not in _NOISE and unresolved < 4:
                unresolved += 1
                steps.append({"depth": level, "from": sym.qualname, "from_file": sym.file, "to": c.removeprefix("?."), "to_file": "", "to_line": 0, "resolved": False, "verified": False, "label": f"{c.removeprefix('?.')}()", "id": None, "kind": "call"})
        # React/JSX: components rendered by this function (`<Header />`) are uses of those components, in order of appearance
        if sym.language in ("javascript", "typescript", "tsx", "jsx") and root_path is not None:
            seen_tags: set[str] = set()
            body = "\n".join(lines_of(sym.file)[max(0, sym.start - 1):sym.end])
            for m in re.finditer(r"<([A-Z][A-Za-z0-9_]*)(?:\.[A-Za-z0-9_]+)*[\s/>]", body):
                tag = m.group(1)
                if tag in seen_tags or len(steps) >= max_steps:
                    continue
                seen_tags.add(tag)
                cands = [c for c in graph.by_name.get(tag, []) if c.kind in ("function", "class", "variable", "method", "const")]
                imported = graph.imports_of.get(sym.file, set())
                ts = next((c for c in cands if c.file == sym.file), None) or next((c for c in cands if c.file in imported), None) or (cands[0] if len(cands) == 1 else None)
                if ts is not None and ts.id != sym.id:
                    steps.append({"depth": level, "from": sym.qualname, "from_file": sym.file, "to": ts.qualname, "to_file": ts.file, "to_line": ts.start, "resolved": True, "verified": ts.file in imported or ts.file == sym.file, "label": f"<{tag} />", "id": ts.id, "kind": "render"})
                    if level < depth:
                        visit(ts, level + 1)

    visit(root, 1)
    parts: list[dict] = []
    for f in [root.file] + [x for s in steps for x in (s["from_file"], s["to_file"])]:
        label = posixpath.basename(f) if f else "(library / unresolved)"
        if not any(p["file"] == f for p in parts):
            parts.append({"file": f, "label": label})
    return {"root": {"id": root.id, "name": root.name, "qualname": root.qualname, "file": root.file, "line": root.start}, "steps": steps, "participants": parts, "truncated": truncated}
