"""Python extraction with the standard `ast` module (exact, no dependencies)."""
from __future__ import annotations
import ast
import io
import tokenize

from .model import ApiRoute, FileFacts, ImportRef, Symbol, TODO_RE, finalize_ids, is_test_path

FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
HTTP = {"get", "post", "put", "patch", "delete", "head", "options"}
STRONG_MODEL_BASES = {"Model", "Document", "EmbeddedDocument"}   # a subclass of these is an ORM model
WEAK_MODEL_BASES = {"Base", "Entity", "DeclarativeBase"}   # common names for other things too: only a model if it also declares columns
DB_FIELD_CALLS = {"Column", "mapped_column", "relationship", "ForeignKey", "CharField", "IntegerField", "TextField", "BooleanField",
                  "DateTimeField", "DateField", "FloatField", "DecimalField", "JSONField", "UUIDField", "EmailField", "URLField"}
def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else f"?.{node.attr}"
    return ""


def calls_in(node: ast.AST) -> list[str]:
    """Callee names used in a function body (decorators are excluded: they run at definition time, not per call)."""
    seen: dict[str, None] = {}
    roots = node.body if isinstance(node, FUNCS) else [node]
    for root in roots:
        for n in ast.walk(root):
            if isinstance(n, ast.Call):
                name = dotted(n.func)
                if name:
                    seen.setdefault(name, None)
    return list(seen)


def _span(node) -> tuple[int, int]:
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return start, node.end_lineno or node.lineno


def _doc(node) -> str:
    d = ast.get_docstring(node)
    return " ".join(d.split())[:300] if d else ""


def _unparse(node, limit=120) -> str:
    try:
        return ast.unparse(node)[:limit]
    except Exception:  # noqa: BLE001
        return ""


def _signature(node) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(_unparse(b) for b in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    ret = f" -> {_unparse(node.returns)}" if node.returns else ""
    return f"{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}def {node.name}({_unparse(node.args, 160)}){ret}"


def _router_prefixes(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            fname = dotted(n.value.func).split(".")[-1]
            if fname in ("APIRouter", "Blueprint", "Router"):
                for kw in n.value.keywords:
                    if kw.arg in ("prefix", "url_prefix") and isinstance(kw.value, ast.Constant):
                        for t in n.targets:
                            if isinstance(t, ast.Name):
                                out[t.id] = str(kw.value.value)
    return out


def _routes(node, prefixes: dict[str, str]) -> list[tuple[str, str, str]]:
    """[(method, path, framework)] from decorators like @app.get('/x'), @app.route('/x', methods=[...]), @app.websocket('/ws')."""
    out = []
    for d in getattr(node, "decorator_list", []):
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args
                and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str)):
            continue
        attr, owner = d.func.attr, dotted(d.func.value)
        path = prefixes.get(owner, "") + d.args[0].value
        if attr in HTTP:
            out.append((attr.upper(), path, "fastapi/flask"))
        elif attr in ("route", "api_route"):
            methods = ["GET"]
            for kw in d.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    got = [e.value.upper() for e in kw.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                    methods = got or methods
            out.append(("|".join(methods), path, "flask"))
        elif attr == "websocket":
            out.append(("WS", path, "fastapi"))
    return out


def _class_info(node: ast.ClassDef) -> tuple[list[str], list[str], dict]:
    bases = [_unparse(b) for b in node.bases]
    tags, extra = [], {}
    short = {b.split(".")[-1] for b in bases}
    if short & {"Protocol", "ABC"} or any(k.arg == "metaclass" and "ABCMeta" in _unparse(k.value) for k in node.keywords):
        tags.append("interface")
    fields_ = []
    has_tablename = False
    for st in node.body:
        targets = [t for t in (st.targets if isinstance(st, ast.Assign) else [st.target] if isinstance(st, ast.AnnAssign) else []) if isinstance(t, ast.Name)]
        value = getattr(st, "value", None)
        if any(t.id in ("__tablename__", "__table__") for t in targets):
            has_tablename = True
        if isinstance(value, ast.Call) and dotted(value.func).split(".")[-1] in DB_FIELD_CALLS:
            fields_ += [t.id for t in targets]
    table_true = any(k.arg == "table" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)
    is_model = bool(short & STRONG_MODEL_BASES) or has_tablename or table_true or bool(fields_ and short)
    if short & WEAK_MODEL_BASES and fields_:
        is_model = True
    if is_model:
        tags.append("model")
        fw = "django" if any(b.startswith("models.") for b in bases) else "sqlalchemy/orm"
        extra = {"framework": fw, "fields": fields_[:40]}
    return bases, tags, extra


def extract_python(path: str, text: str) -> FileFacts:
    tree = ast.parse(text)  # SyntaxError is handled by the caller (falls back to Tree-sitter)
    lines = text.splitlines()
    facts = FileFacts(path=path, language="python", lines=len(lines), parser="python-ast", is_test=is_test_path(path),
                      module_doc=_doc(tree))
    prefixes = _router_prefixes(tree)
    syms = facts.symbols

    def add(kind, name, qual, node, parent="", **kw) -> Symbol:
        s, e = _span(node) if hasattr(node, "lineno") else (0, 0)
        sym = Symbol(file=path, language="python", kind=kind, name=name, qualname=qual, start=s, end=e, parent=parent, **kw)
        syms.append(sym)
        return sym

    def visit_func(node, prefix: str, parent: str) -> None:
        qual = f"{prefix}{node.name}"
        kind = "method" if parent else "function"
        tags = ["async"] if isinstance(node, ast.AsyncFunctionDef) else []
        is_test = node.name.startswith("test") and (facts.is_test or parent.split(".")[-1].startswith("Test"))
        if is_test:
            tags.append("test")
            facts.tests.append({"name": qual, "line": node.lineno})
        routes = _routes(node, prefixes)
        route = f"{routes[0][0]} {routes[0][1]}" if routes else ""
        for m, p, fw in routes:
            facts.apis.append(ApiRoute(m, p, qual, node.lineno, fw))
        if routes:
            tags.append("api")
        add(kind, node.name, qual, node, parent, signature=_signature(node), doc=_doc(node), calls=calls_in(node),
            decorators=[_unparse(d, 80) for d in node.decorator_list], tags=tags, route=route, exported=not node.name.startswith("_"))

    def visit_class(node: ast.ClassDef, prefix: str, parent: str) -> None:
        qual = f"{prefix}{node.name}"
        bases, tags, extra = _class_info(node)
        if node.name.startswith("Test") and facts.is_test:
            tags.append("test")
        add("class", node.name, qual, node, parent, signature=_signature(node), doc=_doc(node), bases=bases, tags=tags,
            decorators=[_unparse(d, 80) for d in node.decorator_list], exported=not node.name.startswith("_"), extra=extra)
        for st in node.body:
            if isinstance(st, FUNCS):
                visit_func(st, f"{qual}.", qual)
            elif isinstance(st, ast.ClassDef):
                visit_class(st, f"{qual}.", qual)
            else:
                visit_var(st, qual)

    def visit_var(st, parent: str) -> None:
        targets = st.targets if isinstance(st, ast.Assign) else [st.target] if isinstance(st, ast.AnnAssign) else []
        for t in targets:
            if isinstance(t, ast.Name) and not (t.id.startswith("__") and t.id.endswith("__")) and len([x for x in syms if x.kind in ("variable", "constant")]) < 300:
                qual = f"{parent}.{t.id}" if parent else t.id
                add("constant" if t.id.isupper() else "variable", t.id, qual, st, parent, exported=not t.id.startswith("_"),
                    signature=_unparse(st, 100))

    def walk_body(body) -> None:
        for st in body:
            if isinstance(st, FUNCS):
                visit_func(st, "", "")
            elif isinstance(st, ast.ClassDef):
                visit_class(st, "", "")
            elif isinstance(st, (ast.Assign, ast.AnnAssign)):
                visit_var(st, "")
                _django_urls(st)
            elif isinstance(st, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                for attr in ("body", "orelse", "finalbody"):
                    walk_body(getattr(st, attr, []))
                for h in getattr(st, "handlers", []):
                    walk_body(h.body)

    def _django_urls(st) -> None:
        value = getattr(st, "value", None)
        if not (isinstance(value, (ast.List, ast.Tuple))):
            return
        for el in value.elts:
            if isinstance(el, ast.Call) and dotted(el.func).split(".")[-1] in ("path", "re_path", "url") and len(el.args) >= 2:
                a0 = el.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    handler = dotted(el.args[1]).split(".")[-1] or ("include" if isinstance(el.args[1], ast.Call) else "")
                    facts.apis.append(ApiRoute("ANY", "/" + a0.value.lstrip("^/"), handler, el.lineno, "django"))

    walk_body(tree.body)

    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            facts.imports += [ImportRef(module=a.name, alias=a.asname or "", line=n.lineno) for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            facts.imports.append(ImportRef(module=n.module or "", level=n.level, line=n.lineno,
                                           names=[[a.name, a.asname or ""] for a in n.names]))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                facts.comment_lines += 1
                m = TODO_RE.search(tok.string)
                if m:
                    facts.todos.append({"line": tok.start[0], "text": f"{m.group(1).upper()}: {m.group(2).strip()}"[:160]})
    except (tokenize.TokenError, IndentationError):
        pass
    finalize_ids(facts)
    return facts
