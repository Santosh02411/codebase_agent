"""Repository graphs built from per-file facts: module (import) graph, call graph, inheritance graph, impact analysis."""
from __future__ import annotations
import posixpath
from collections import defaultdict, deque
from dataclasses import dataclass

from .model import FileFacts, ImportRef, Symbol

CALLABLE = {"function", "method", "class", "struct"}
TYPE_KINDS = {"class", "interface", "struct", "trait", "enum", "type"}
COMMON = {"get", "set", "add", "remove", "append", "push", "pop", "run", "start", "stop", "close", "open", "read", "write", "update",
          "delete", "create", "init", "main", "test", "print", "len", "map", "filter", "find", "keys", "values", "items", "join", "split",
          "strip", "format", "send", "call", "apply", "copy", "clear", "reset", "new", "next", "load", "save", "list", "put", "post", "emit",
          "then", "catch", "log", "error", "info", "debug", "warn", "toString", "equals", "hashCode", "size", "length", "contains", "has"}
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json")
SELF_NAMES = {"self", "this", "cls", "super", "Self"}


@dataclass
class ModuleEdge:
    src: str
    dst: str
    names: list[str]
    line: int


class CodeGraph:
    def __init__(self, facts: dict[str, FileFacts], context: dict | None = None) -> None:
        self.facts = facts
        self.ctx = context or {}
        self.symbols: dict[str, Symbol] = {}
        self.by_file: dict[str, list[Symbol]] = {}
        self.by_name: dict[str, list[Symbol]] = defaultdict(list)
        self.module_edges: list[ModuleEdge] = []
        self.imports_of: dict[str, set[str]] = defaultdict(set)
        self.imported_by: dict[str, set[str]] = defaultdict(set)
        self.external: dict[str, set[str]] = defaultdict(set)
        self.call_edges: dict[str, dict[str, str]] = defaultdict(dict)
        self.caller_edges: dict[str, dict[str, str]] = defaultdict(dict)
        self.base_ids: dict[str, list[str]] = {}
        self.ext_bases: dict[str, list[str]] = {}
        self.derived: dict[str, list[str]] = defaultdict(list)
        self.call_total = 0
        self.call_resolved = 0
        self._import_map: dict[str, dict[str, tuple[list[str], str | None]]] = {}
        self._build()

    # ------------------------------------------------------------------ indexes
    def _build(self) -> None:
        files = set(self.facts)
        for path, f in self.facts.items():
            self.by_file[path] = f.symbols
            for s in f.symbols:
                self.symbols[s.id] = s
                self.by_name[s.name].append(s)
        self._index_modules(files)
        for path, f in self.facts.items():
            self._resolve_imports(path, f, files)
        for path, f in self.facts.items():
            for s in f.symbols:
                if s.bases:
                    self._resolve_bases(s)
        for path, f in self.facts.items():
            for s in f.symbols:
                if s.kind in ("function", "method") and s.calls:
                    self._resolve_calls(s)

    def _index_modules(self, files: set[str]) -> None:
        self.py_modules: dict[str, list[str]] = defaultdict(list)
        self.java_types: dict[str, str] = {}
        self.go_dirs: dict[str, list[str]] = defaultdict(list)
        self.basenames: dict[str, list[str]] = defaultdict(list)
        for p in files:
            self.basenames[posixpath.basename(p)].append(p)
            if p.endswith(".py"):
                parts = p[:-3].split("/")
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                for i in range(len(parts)):
                    self.py_modules[".".join(parts[i:])].append(p)
            elif p.endswith(".go"):
                self.go_dirs[posixpath.dirname(p)].append(p)
        for p, f in self.facts.items():
            if p.endswith(".java"):
                for s in f.symbols:
                    if s.kind in TYPE_KINDS and not s.parent:
                        self.java_types[f"{f.package}.{s.name}" if f.package else s.name] = p

    # ------------------------------------------------------------------ module resolution
    @staticmethod
    def _closest(src: str, cands: list[str]) -> str | None:
        if not cands:
            return None
        sd = src.split("/")[:-1]

        def score(c: str) -> tuple[int, int]:
            cd = c.split("/")[:-1]
            common = 0
            for a, b in zip(sd, cd):
                if a != b:
                    break
                common += 1
            return (-common, len(c))
        return sorted(cands, key=score)[0]

    def _py(self, src: str, ref: ImportRef) -> tuple[str | None, dict[str, str]]:
        """-> (module file, {imported name: submodule file})"""
        files = set(self.facts)
        subs: dict[str, str] = {}
        if ref.level > 0:
            base = src.split("/")[:-1]
            if ref.level > 1:
                base = base[: len(base) - (ref.level - 1)] if len(base) >= ref.level - 1 else []
            mod = [m for m in ref.module.split(".") if m]
            path = "/".join(base + mod)
            main = next((c for c in (f"{path}.py", f"{path}/__init__.py") if c in files), None) if (mod or path) else None
            if not mod:
                main = next((c for c in (f"{path}/__init__.py" if path else "__init__.py",) if c in files), None)
            for n, _ in ref.names:
                cand = "/".join(base + mod + [n])
                for c in (f"{cand}.py", f"{cand}/__init__.py"):
                    if c in files:
                        subs[n] = c
            return main, subs
        mod = ref.module
        main = self._closest(src, self.py_modules.get(mod, []))
        for n, _ in ref.names:
            c = self._closest(src, self.py_modules.get(f"{mod}.{n}", []))
            if c:
                subs[n] = c
        return main, subs

    def _js(self, src: str, spec: str) -> str | None:
        files = set(self.facts)
        bases: list[str] = []
        if spec.startswith("."):
            bases = [posixpath.normpath(posixpath.join(posixpath.dirname(src), spec))]
        elif spec.startswith(("@/", "~/")):
            bases = [spec[2:], "src/" + spec[2:]]
        else:
            return None
        for b in bases:
            stem = b.rsplit(".", 1)[0] if b.endswith((".js", ".jsx", ".mjs", ".cjs")) else None
            for cand in [b] + [b + e for e in JS_EXT] + [f"{b}/index{e}" for e in JS_EXT] + ([stem + e for e in JS_EXT] if stem else []):
                if cand in files:
                    return cand
        return None

    def _java(self, ref: ImportRef) -> list[str]:
        mod = ref.module
        if ref.names and ref.names[0][0] == "*":
            return [p for p, f in self.facts.items() if p.endswith(".java") and f.package == mod]
        parts = mod.split(".")
        for k in range(len(parts), 0, -1):
            hit = self.java_types.get(".".join(parts[:k]))
            if hit:
                return [hit]
        tail = "/".join(parts) + ".java"
        return [p for p in self.facts if p.endswith(tail)][:1]

    def _go(self, spec: str) -> list[str]:
        mod, root = self.ctx.get("go_module", ""), self.ctx.get("go_root", "")
        if mod and (spec == mod or spec.startswith(mod + "/")):
            rel = spec[len(mod):].strip("/")
            return self.go_dirs.get(posixpath.normpath(posixpath.join(root, rel)).strip("."), self.go_dirs.get(posixpath.join(root, rel), []))
        parts = spec.split("/")
        for k in range(min(3, len(parts)), 0, -1):
            tail = "/".join(parts[-k:])
            dirs = [d for d in self.go_dirs if d == tail or d.endswith("/" + tail)]
            if len(dirs) == 1:
                return self.go_dirs[dirs[0]]
        return []

    def _c(self, src: str, spec: str, local: bool) -> str | None:
        files = set(self.facts)
        if not local:
            return None
        for cand in (posixpath.normpath(posixpath.join(posixpath.dirname(src), spec)), spec, f"include/{spec}", f"src/{spec}"):
            if cand in files:
                return cand
        hits = self.basenames.get(posixpath.basename(spec), [])
        return self._closest(src, hits) if len(hits) >= 1 else None

    def _rust(self, src: str, path: str, kind: str) -> tuple[str | None, str | None]:
        """-> (module file, remaining item name)"""
        files = set(self.facts)
        segs = [s for s in path.replace("::", "/").split("/") if s and s not in ("{", "}")]
        d, stem = posixpath.dirname(src), posixpath.basename(src)[:-3]
        cur = d if stem in ("mod", "lib", "main") else posixpath.join(d, stem)
        parts = src.split("/")
        root = "/".join(parts[: parts.index("src") + 1]) if "src" in parts else d
        if kind == "mod":
            base, rest = cur, segs
        elif segs and segs[0] == "crate":
            base, rest = root, segs[1:]
        elif segs and segs[0] == "self":
            base, rest = cur, segs[1:]
        elif segs and segs[0] == "super":
            base, rest = posixpath.dirname(cur), segs[1:]
            while rest and rest[0] == "super":
                base, rest = posixpath.dirname(base), rest[1:]
        else:
            return None, None
        for k in range(len(rest), 0, -1):
            p = posixpath.join(base, *rest[:k])
            for c in (f"{p}.rs", f"{p}/mod.rs"):
                if c in files:
                    return c, (rest[k] if k < len(rest) else None)
        return None, None

    # ------------------------------------------------------------------ imports
    def _resolve_imports(self, path: str, f: FileFacts, files: set[str]) -> None:
        imap: dict[str, tuple[list[str], str | None]] = {}
        lang = f.language

        def link(targets: list[str], names: list[str], line: int) -> None:
            for t in targets:
                if t != path:
                    self.module_edges.append(ModuleEdge(path, t, names, line))
                    self.imports_of[path].add(t)
                    self.imported_by[t].add(path)

        for ref in f.imports:
            if lang == "python":
                main, subs = self._py(path, ref)
                targets = ([main] if main else []) + list(subs.values())
                if targets:
                    link(targets, [n for n, _ in ref.names] or [ref.module], ref.line)
                else:
                    if ref.level == 0 and ref.module:
                        self.external[path].add(ref.module.split(".")[0])
                    continue
                if main and ref.alias:
                    imap[ref.alias] = ([main], None)
                elif main and not ref.names:
                    imap[ref.module] = ([main], None)
                    imap.setdefault(ref.module.split(".")[0], ([main], None))
                for n, a in ref.names:
                    if n in subs:
                        imap[a or n] = ([subs[n]], None)
                    elif main:
                        imap[a or n] = ([main], n)
            elif lang in ("javascript", "typescript"):
                t = self._js(path, ref.module)
                if not t:
                    if not ref.module.startswith("."):
                        parts = ref.module.split("/")
                        self.external[path].add("/".join(parts[:2]) if ref.module.startswith("@") else parts[0])
                    continue
                link([t], [n for n, _ in ref.names], ref.line)
                if ref.alias:
                    imap[ref.alias] = ([t], None)
                for n, a in ref.names:
                    imap[a or n] = ([t], n)
            elif lang == "java":
                targets = self._java(ref)
                if not targets:
                    self.external[path].add(".".join(ref.module.split(".")[:2]))
                    continue
                link(targets, [ref.module.split(".")[-1]], ref.line)
                if not (ref.names and ref.names[0][0] == "*"):
                    imap[ref.module.split(".")[-1]] = (targets, ref.module.split(".")[-1])
            elif lang == "go":
                targets = self._go(ref.module)
                if not targets:
                    self.external[path].add(ref.module)
                    continue
                link(targets[:20], [ref.module.split("/")[-1]], ref.line)
                imap[ref.alias or ref.module.split("/")[-1]] = (targets, None)
            elif lang in ("c", "cpp"):
                t = self._c(path, ref.module, ref.level == 1)
                if t:
                    link([t], [], ref.line)
                else:
                    self.external[path].add(ref.module)
            elif lang == "rust":
                t, item = self._rust(path, ref.module, ref.kind)
                if not t:
                    top = ref.module.replace("::", "/").split("/")[0]
                    if top not in ("crate", "self", "super", "std", "core", "alloc"):
                        self.external[path].add(top)
                    continue
                link([t], [n for n, _ in ref.names] or ([item] if item else []), ref.line)
                if ref.kind == "mod":
                    imap[ref.module] = ([t], None)
                for n, a in ref.names:
                    imap[a or n] = ([t], n)
                if not ref.names:
                    last = ref.alias or ref.module.replace("::", "/").split("/")[-1]
                    imap[last] = ([t], item)
        self._import_map[path] = imap

    # ------------------------------------------------------------------ inheritance
    def _lookup_type(self, f: str, name: str) -> list[Symbol]:
        for s in self.by_file.get(f, []):
            if s.name == name and s.kind in TYPE_KINDS and not s.parent:
                return [s]
        imp = self._import_map.get(f, {}).get(name)
        if imp:
            files, orig = imp
            for ff in files:
                for s in self.by_file.get(ff, []):
                    if s.name == (orig if orig and orig != "default" else name) and s.kind in TYPE_KINDS:
                        return [s]
        cands = [s for s in self.by_name.get(name, []) if s.kind in TYPE_KINDS]
        return cands if len(cands) == 1 else []

    def _resolve_bases(self, s: Symbol) -> None:
        ids, ext = [], []
        for b in s.bases:
            short = b.split(".")[-1].strip()
            hit = self._lookup_type(s.file, short)
            if hit and hit[0].id != s.id:
                ids.append(hit[0].id)
                self.derived[hit[0].id].append(s.id)
            else:
                ext.append(b)
        self.base_ids[s.id] = ids
        if ext:
            self.ext_bases[s.id] = ext

    def ancestors(self, class_id: str) -> list[str]:
        out, seen, q = [], {class_id}, deque([class_id])
        while q:
            for b in self.base_ids.get(q.popleft(), []):
                if b not in seen:
                    seen.add(b); out.append(b); q.append(b)
        return out

    # ------------------------------------------------------------------ calls
    def _method_in(self, class_sym: Symbol, name: str) -> Symbol | None:
        for cid in [class_sym.id] + self.ancestors(class_sym.id):
            c = self.symbols[cid]
            for s in self.by_file.get(c.file, []):
                if s.parent == c.qualname and s.name == name and s.kind in ("method", "function"):
                    return s
        return None

    def _top(self, f: str, name: str) -> Symbol | None:
        for s in self.by_file.get(f, []):
            if s.name == name and not s.parent and s.kind in CALLABLE:
                return s
        return None

    def _in_files(self, files: list[str], name: str) -> Symbol | None:
        for ff in files:
            hit = self._top(ff, name)
            if hit:
                return hit
        return None

    def _enclosing_class(self, s: Symbol) -> Symbol | None:
        if not s.parent:
            return None
        for c in self.by_file.get(s.file, []):
            if c.qualname == s.parent and c.kind in TYPE_KINDS:
                return c
        return None

    def _targets(self, s: Symbol, callee: str) -> list[tuple[Symbol, str]]:
        parts = callee.split(".")
        name, recv = parts[-1], parts[:-1]
        f, imap = s.file, self._import_map.get(s.file, {})
        if not name or name == "?":
            return []
        if not recv:
            hit = self._top(f, name)
            if hit:
                return [(hit, "local")]
            enc = self._enclosing_class(s)
            if enc:  # unqualified call inside a class (Java/C++/Go-style implicit receiver)
                m = self._method_in(enc, name)
                if m and m.id != s.id:
                    return [(m, "self")]
            imp = imap.get(name)
            if imp:
                files, orig = imp
                target = orig if orig and orig != "default" else name
                hit = self._in_files(files, target) or (self._in_files(files, name) if orig == "default" else None)
                if hit is None and orig == "default":
                    exported = [x for ff in files for x in self.by_file.get(ff, []) if x.exported and x.kind in CALLABLE and not x.parent]
                    hit = exported[0] if len(exported) == 1 else None
                if hit:
                    return [(hit, "import")]
            cands = [x for x in self.by_name.get(name, []) if x.kind in CALLABLE and x.id != s.id]
            if len(cands) == 1:
                return [(cands[0], "unique")]
            if 1 < len(cands) <= 3 and len(name) > 3 and name not in COMMON:
                return [(c, "ambiguous") for c in cands]
            return []
        head = recv[0]
        if head in SELF_NAMES and len(recv) == 1:
            enc = self._enclosing_class(s)
            if enc:
                m = self._method_in(enc, name)
                if m and m.id != s.id:
                    return [(m, "self")]
            return []
        for k in range(len(recv), 0, -1):  # longest imported-module prefix: a.b.func / u.func
            imp = imap.get(".".join(recv[:k]))
            if imp:
                files, orig = imp
                if orig is None:
                    if k == len(recv):
                        hit = self._in_files(files, name)
                        if hit:
                            return [(hit, "import")]
                    else:  # module.Class.method
                        cls = self._in_files(files, recv[k])
                        if cls and cls.kind in TYPE_KINDS:
                            m = self._method_in(cls, name)
                            if m:
                                return [(m, "import")]
                else:  # imported name used as receiver: Class.method / obj.method
                    target = orig if orig != "default" else recv[k - 1]
                    cls = self._in_files(files, target)
                    if cls and cls.kind in TYPE_KINDS:
                        m = self._method_in(cls, name)
                        if m:
                            return [(m, "import")]
                break
        cls_name = recv[-1]
        for cls in self._lookup_type(f, cls_name):
            m = self._method_in(cls, name)
            if m:
                return [(m, "class")]
        if name in COMMON:
            return []
        cands = [x for x in self.by_name.get(name, []) if x.kind == "method" and x.id != s.id]
        return [(cands[0], "unique")] if len(cands) == 1 else []

    def _resolve_calls(self, s: Symbol) -> None:
        for callee in s.calls:
            self.call_total += 1
            hits = self._targets(s, callee)
            if hits:
                self.call_resolved += 1
            for t, conf in hits:
                if t.id != s.id:
                    self.call_edges[s.id].setdefault(t.id, conf)
                    self.caller_edges[t.id].setdefault(s.id, conf)

    # ------------------------------------------------------------------ queries
    def callees(self, sid: str) -> list[tuple[Symbol, str]]:
        return [(self.symbols[k], c) for k, c in self.call_edges.get(sid, {}).items()]

    def callers(self, sid: str) -> list[tuple[Symbol, str]]:
        return [(self.symbols[k], c) for k, c in self.caller_edges.get(sid, {}).items()]

    def find(self, name: str) -> list[Symbol]:
        return list(self.by_name.get(name, [])) or [s for s in self.symbols.values() if s.qualname == name]

    def dependents(self, path: str, depth: int = 3) -> dict[str, int]:
        """Files that (transitively) import `path`, with their distance."""
        out: dict[str, int] = {}
        q = deque([(path, 0)])
        while q:
            cur, d = q.popleft()
            if d >= depth:
                continue
            for p in self.imported_by.get(cur, ()):
                if p != path and p not in out:
                    out[p] = d + 1
                    q.append((p, d + 1))
        return out

    def impact(self, path: str, depth: int = 3) -> dict:
        deps = self.dependents(path, depth)
        tests = sorted(p for p in deps if self.facts[p].is_test)
        if self.facts.get(path) and not self.facts[path].is_test:
            stem = posixpath.basename(path).split(".")[0]
            tests += sorted(p for p, f in self.facts.items() if f.is_test and stem in posixpath.basename(p) and p not in tests)
        return {"file": path, "dependents": [{"file": p, "distance": d} for p, d in sorted(deps.items(), key=lambda x: (x[1], x[0]))],
                "tests": tests}

    def call_subgraph(self, sid: str, depth: int = 2, direction: str = "both", limit: int = 60) -> dict:
        if sid not in self.symbols:
            return {"nodes": [], "edges": []}
        nodes: dict[str, int] = {sid: 0}
        edges: list[dict] = []
        for want, table, sign in (("callees", self.call_edges, 1), ("callers", self.caller_edges, -1)):
            if direction not in ("both", want):
                continue
            q = deque([(sid, 0)])
            seen = {sid}
            while q:
                cur, d = q.popleft()
                if d >= depth:
                    continue
                for nxt, conf in table.get(cur, {}).items():
                    if len(nodes) >= limit and nxt not in nodes:
                        continue
                    edges.append({"source": cur, "target": nxt, "confidence": conf} if sign == 1 else {"source": nxt, "target": cur, "confidence": conf})
                    if nxt not in seen:
                        seen.add(nxt)
                        nodes.setdefault(nxt, sign * (d + 1))
                        q.append((nxt, d + 1))
        uniq = {(e["source"], e["target"]): e for e in edges}
        return {"nodes": [self._node(i, lvl) for i, lvl in nodes.items()], "edges": list(uniq.values())}

    def _node(self, sid: str, level: int) -> dict:
        s = self.symbols[sid]
        return {"id": s.id, "name": s.name, "qualname": s.qualname, "file": s.file, "kind": s.kind, "start": s.start, "end": s.end,
                "level": level, "route": s.route, "signature": s.signature}

    def module_subgraph(self, path: str, depth: int = 1, direction: str = "both", limit: int = 60) -> dict:
        nodes: dict[str, int] = {path: 0}
        edges: set[tuple[str, str]] = set()
        for want, table, sign in (("imports", self.imports_of, 1), ("imported_by", self.imported_by, -1)):
            if direction not in ("both", want):
                continue
            q, seen = deque([(path, 0)]), {path}
            while q:
                cur, d = q.popleft()
                if d >= depth:
                    continue
                for nxt in sorted(table.get(cur, ())):
                    if len(nodes) >= limit and nxt not in nodes:
                        continue
                    edges.add((cur, nxt) if sign == 1 else (nxt, cur))
                    if nxt not in seen:
                        seen.add(nxt); nodes.setdefault(nxt, sign * (d + 1)); q.append((nxt, d + 1))
        return {"nodes": [{"id": p, "name": posixpath.basename(p), "file": p, "level": lvl, "language": self.facts[p].language,
                           "symbols": len(self.facts[p].symbols), "external": sorted(self.external.get(p, ()))[:12]} for p, lvl in nodes.items()],
                "edges": [{"source": a, "target": b} for a, b in sorted(edges)]}

    def modules_overview(self, limit: int = 80) -> dict:
        """Whole-repo module graph. Large repos are collapsed to directories so the picture stays readable."""
        files = [p for p, f in self.facts.items() if f.language in ("python", "javascript", "typescript", "java", "go", "rust", "c", "cpp")]
        if len(files) <= limit:
            nodes = [{"id": p, "name": posixpath.basename(p), "file": p, "count": 1, "kind": "file"} for p in files]
            edges = [{"source": a, "target": b, "weight": 1} for a, b in sorted({(e.src, e.dst) for e in self.module_edges})]
            return {"collapsed": False, "nodes": nodes, "edges": edges}

        def group(p: str) -> str:
            parts = p.split("/")[:-1]
            return "/".join(parts[:2]) or "."
        counts: dict[str, int] = defaultdict(int)
        for p in files:
            counts[group(p)] += 1
        weights: dict[tuple[str, str], int] = defaultdict(int)
        for e in self.module_edges:
            a, b = group(e.src), group(e.dst)
            if a != b:
                weights[(a, b)] += 1
        return {"collapsed": True,
                "nodes": [{"id": g, "name": g, "file": g, "count": c, "kind": "directory"} for g, c in sorted(counts.items(), key=lambda x: -x[1])[:limit]],
                "edges": [{"source": a, "target": b, "weight": w} for (a, b), w in sorted(weights.items(), key=lambda x: -x[1]) if a in counts and b in counts]}
