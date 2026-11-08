"""Strict, deterministic analysis of Python source. No model, no guessing about intent: every finding is something Python itself would reject,
raise at run time, or that is a well-known bug pattern. Rules and confidence are explicit.

  PY-SYNTAX      the file does not compile (Python's own message, line and column)
  PY-UNDEFINED   a name is read but never defined anywhere it can be seen from (with a "did you mean" from the names in scope)
  PY-ATTR        `self.x` is read but never assigned in the class (typos), only when the class's bases are all known
  PY-MODATTR     `os.pth` : a standard-library module has no such attribute
  PY-IMPORT      importing a name or module that does not exist in this project
  PY-ARITY       calling a function of this project with the wrong number of arguments / an unknown keyword
  PY-...         unused imports and variables, redefinitions, `assert (x, "msg")`, `is` with literals, `x / 0`, string + int, format-count mismatches,
                 unreachable code, swallowed exceptions, mutable defaults, and a set of security patterns."""
from __future__ import annotations
import ast
import builtins
import difflib
import importlib
import re
import sys
import warnings
from dataclasses import dataclass, field

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__", "__builtins__", "__path__", "__annotations__", "__debug__", "__class__", "__qualname__", "__module__"}
PY2 = {"unicode", "xrange", "raw_input", "basestring", "long", "reduce", "cmp", "unichr", "execfile", "file", "reload", "iteritems"}
SAFE_STDLIB = {"os", "sys", "re", "json", "math", "time", "datetime", "random", "pathlib", "collections", "itertools", "functools", "string", "typing", "subprocess", "shutil", "logging",
               "uuid", "hashlib", "base64", "copy", "csv", "io", "urllib", "threading", "tempfile", "glob", "statistics", "decimal", "enum", "dataclasses", "abc", "operator", "textwrap",
               "traceback", "warnings", "inspect", "secrets", "heapq", "bisect", "fnmatch", "zipfile", "sqlite3", "argparse", "contextlib", "platform", "unittest", "asyncio", "queue", "struct"}
PLATFORM_ONLY = {"getuid", "geteuid", "getgid", "getegid", "fork", "killpg", "getpgid", "startfile", "geteuid", "setuid", "setgid", "O_BINARY", "getlogin", "uname", "WNOHANG", "getppid", "nice", "chown", "getloadavg"}


@dataclass
class Finding:
    rule: str
    category: str
    severity: str
    message: str
    line: int
    col: int = 0
    end_col: int = 0
    confidence: str = "high"
    fix: str = ""
    extra: dict = field(default_factory=dict)


def _suggest(name: str, pool, n: int = 1) -> list[str]:
    return difflib.get_close_matches(name, [p for p in pool if p and p != name], n=n, cutoff=0.72)


def _did_you_mean(name: str, pool) -> str:
    s = _suggest(name, pool)
    return f" Did you mean `{s[0]}`?" if s else ""


# ---- project context (module resolution, exports and signatures of other files) ------------------------------------------------------
@dataclass
class Sig:
    params: list[str]               # positional-capable parameter names in order (self/cls removed for methods)
    required: int                   # number of leading params without default
    kwonly: list[str]
    kwonly_required: list[str]
    varargs: bool
    varkw: bool
    posonly: int = 0


def make_sig(fn: ast.FunctionDef | ast.AsyncFunctionDef, drop_first: bool = False) -> Sig:
    a = fn.args
    pos = [p.arg for p in a.posonlyargs] + [p.arg for p in a.args]
    ndef = len(a.defaults)
    req = len(pos) - ndef
    if drop_first and pos:
        pos = pos[1:]; req = max(0, req - 1)
    kw = [p.arg for p in a.kwonlyargs]
    kwreq = [p.arg for p, d in zip(a.kwonlyargs, a.kw_defaults) if d is None]
    return Sig(pos, max(0, req), kw, kwreq, a.vararg is not None, a.kwarg is not None, len(a.posonlyargs))


class Project:
    """What other files of the project define: used to validate imports and calls across files."""
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.mod_to_file: dict[str, str] = {}
        for f in files:
            if f.endswith(".py"):
                mod = f[:-3].replace("/", ".")
                if mod.endswith(".__init__"):
                    mod = mod[: -len(".__init__")]
                self.mod_to_file[mod] = f
        self.tops = {m.split(".")[0] for m in self.mod_to_file}
        self._exports: dict[str, tuple[set[str], dict[str, Sig], bool] | None] = {}

    def module_file(self, dotted: str) -> str | None:
        return self.mod_to_file.get(dotted)

    def is_package(self, dotted: str) -> bool:
        return any(m == dotted or m.startswith(dotted + ".") for m in self.mod_to_file) and not (dotted in self.mod_to_file and not self.mod_to_file[dotted].endswith("__init__.py") and not any(m.startswith(dotted + ".") for m in self.mod_to_file))

    def submodules(self, dotted: str) -> set[str]:
        pre = dotted + "."
        return {m[len(pre):].split(".")[0] for m in self.mod_to_file if m.startswith(pre)}

    def exports(self, file: str):
        """(top-level names, {function name: Sig}, open) for a file. `open` = the module can define names we cannot see (star import, __getattr__)."""
        if file in self._exports:
            return self._exports[file]
        res = None
        try:
            tree = ast.parse(self.files[file])
        except (SyntaxError, ValueError, KeyError):
            self._exports[file] = None
            return None
        names: set[str] = set(); sigs: dict[str, Sig] = {}; open_ = False
        for n in tree.body:
            for node in ([n] if not isinstance(n, (ast.If, ast.Try)) else list(ast.walk(n))):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(node.name)
                    if node is n and not node.decorator_list:
                        sigs[node.name] = make_sig(node)
                elif isinstance(node, ast.ClassDef):
                    names.add(node.name)
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                        for x in ast.walk(t):
                            if isinstance(x, ast.Name):
                                names.add(x.id)
                elif isinstance(node, ast.Import):
                    for a in node.names:
                        names.add((a.asname or a.name).split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    for a in node.names:
                        if a.name == "*":
                            open_ = True
                        else:
                            names.add(a.asname or a.name)
                elif isinstance(node, (ast.For, ast.With)):
                    for x in ast.walk(node):
                        if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                            names.add(x.id)
        if "__getattr__" in names:
            open_ = True
        res = (names, sigs, open_)
        self._exports[file] = res
        return res

    def resolve_from(self, file: str, module: str | None, level: int) -> str | None:
        """Dotted absolute module name for `from <module> import ...` seen in `file` (None if it cannot be determined)."""
        if level == 0:
            return module or ""
        parts = file[:-3].split("/") if file.endswith(".py") else file.split("/")
        pkg = parts[:-1]
        if file.endswith("__init__.py"):
            pkg = parts[:-1]
        up = level - 1
        if up > len(pkg):
            return None
        base = pkg[: len(pkg) - up] if up else pkg
        return ".".join(base + ([module] if module else []))


# ---- scopes ----------------------------------------------------------------------------------------------------------------------------------
class Scope:
    def __init__(self, kind: str, node: ast.AST | None, parent: "Scope | None") -> None:
        self.kind, self.node, self.parent = kind, node, parent
        self.bound: dict[str, ast.AST] = {}
        self.used: set[str] = set()
        self.star = False
        self.declared_global: set[str] = set()
        self.declared_nonlocal: set[str] = set()
        self.dynamic = False           # uses locals()/vars()/exec/eval: we cannot know which names are used


def _targets(t: ast.AST):
    if isinstance(t, ast.Name):
        yield t
    elif isinstance(t, (ast.Tuple, ast.List)):
        for e in t.elts:
            yield from _targets(e)
    elif isinstance(t, ast.Starred):
        yield from _targets(t.value)


def _bind_stmts(body, scope: Scope, imports: list | None = None) -> None:
    """Collect the names a block binds in `scope` (not descending into nested function/class bodies)."""
    for st in body:
        _bind_stmt(st, scope, imports)


def _bind_stmt(st: ast.AST, scope: Scope, imports) -> None:
    b = scope.bound
    if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        b.setdefault(st.name, st)
        return
    if isinstance(st, ast.Import):
        for a in st.names:
            nm = (a.asname or a.name).split(".")[0]
            b.setdefault(nm, st)
            if imports is not None:
                imports.append((nm, st, a))
        return
    if isinstance(st, ast.ImportFrom):
        for a in st.names:
            if a.name == "*":
                scope.star = True
            else:
                nm = a.asname or a.name
                b.setdefault(nm, st)
                if imports is not None and st.module != "__future__":
                    imports.append((nm, st, a))
        return
    if isinstance(st, (ast.Global,)):
        scope.declared_global.update(st.names); return
    if isinstance(st, ast.Nonlocal):
        scope.declared_nonlocal.update(st.names); return
    for fld, val in ast.iter_fields(st):
        if isinstance(st, ast.Assign) and fld == "targets":
            for t in val:
                for n in _targets(t):
                    b.setdefault(n.id, st)
        elif isinstance(st, (ast.AugAssign, ast.AnnAssign)) and fld == "target":
            for n in _targets(val):
                b.setdefault(n.id, st)
        elif isinstance(st, (ast.For, ast.AsyncFor)) and fld == "target":
            for n in _targets(val):
                b.setdefault(n.id, st)
        elif isinstance(st, (ast.With, ast.AsyncWith)) and fld == "items":
            for it in val:
                if it.optional_vars is not None:
                    for n in _targets(it.optional_vars):
                        b.setdefault(n.id, st)
        elif isinstance(st, ast.ExceptHandler) and fld == "name" and val:
            b.setdefault(val, st)
        elif isinstance(st, ast.Try) and fld in ("body", "orelse", "finalbody"):
            _bind_stmts(val, scope, imports)
        elif isinstance(st, ast.Try) and fld == "handlers":
            for h in val:
                if h.name:
                    b.setdefault(h.name, h)
                _bind_stmts(h.body, scope, imports)
        elif isinstance(st, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)) and fld in ("body", "orelse"):
            _bind_stmts(val, scope, imports)
        elif hasattr(ast, "Match") and isinstance(st, ast.Match) and fld == "cases":
            for c in val:
                for x in ast.walk(c.pattern):
                    for nm in (getattr(x, "name", None), getattr(x, "rest", None)):
                        if isinstance(nm, str):
                            b.setdefault(nm, st)
                _bind_stmts(c.body, scope, imports)
    # walrus anywhere in the statement's expressions
    for x in ast.walk(st):
        if isinstance(x, ast.NamedExpr) and isinstance(x.target, ast.Name):
            b.setdefault(x.target.id, st)
        if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)) and x is not st:
            continue


class Checker(ast.NodeVisitor):
    def __init__(self, path: str, text: str, tree: ast.Module, project: Project) -> None:
        self.path, self.lines, self.tree, self.project = path, text.splitlines(), tree, project
        self.out: list[Finding] = []
        self.module = Scope("module", tree, None)
        self.scope = self.module
        self.future_annotations = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names) for n in tree.body)
        self.suppress = 0
        self.imports: list = []
        self.import_binding: dict[str, tuple[str, str] | tuple[str, None]] = {}   # name -> (project file, original name) for `from X import f`
        self.stdlib_alias: dict[str, str] = {}
        self.local_sigs: dict[str, Sig] = {}
        self.class_stack: list[ast.ClassDef] = []
        self.method_of: dict[ast.AST, ast.ClassDef] = {}
        self.class_info: dict[ast.ClassDef, dict] = {}
        self.all_names: set[str] = set()
        self._prepare()

    # -- setup ------------------------------------------------------------------------------------------------------------------------------
    def _prepare(self) -> None:
        _bind_stmts(self.tree.body, self.module, self.imports)
        for n in self.tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.decorator_list:
                self.local_sigs[n.name] = make_sig(n)
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets) and isinstance(n.value, (ast.List, ast.Tuple)):
                self.all_names |= {e.value for e in n.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        for nm, st, alias in self.imports:
            if isinstance(st, ast.Import):
                top = alias.name.split(".")[0]
                if (alias.asname or top) == nm and top in SAFE_STDLIB and top not in self.project.tops:
                    self.stdlib_alias[nm] = alias.name if alias.asname else top
            elif isinstance(st, ast.ImportFrom):
                mod = self.project.resolve_from(self.path, st.module, st.level)
                if mod is not None:
                    f = self.project.module_file(mod)
                    if f:
                        self.import_binding[nm] = (f, alias.name)

    def add(self, rule, category, severity, msg, node, **kw) -> None:
        self.out.append(Finding(rule, category, severity, msg, getattr(node, "lineno", 1), getattr(node, "col_offset", 0), getattr(node, "end_col_offset", 0) or 0, **kw))

    # -- name lookup -------------------------------------------------------------------------------------------------------------------------
    def _visible(self, name: str, include_class: bool = True):
        s = self.scope; first = True
        while s is not None:
            if name in s.bound or name in s.declared_global:
                if s.kind != "class" or first:
                    return s
            if s.kind == "class" and not first:
                s = s.parent; continue
            first = False
            s = s.parent
        return None

    def _all_visible_names(self) -> set[str]:
        names: set[str] = set(); s = self.scope; first = True
        while s is not None:
            if s.kind != "class" or first:
                names |= set(s.bound)
            first = False
            s = s.parent
        return names | BUILTINS

    def _star_anywhere(self) -> bool:
        s = self.scope
        while s is not None:
            if s.star:
                return True
            s = s.parent
        return False

    def _load(self, node: ast.Name) -> None:
        name = node.id
        sc = self._visible(name)
        if sc is not None:
            sc.used.add(name)
            return
        if name in BUILTINS:
            return
        if self.suppress or self._star_anywhere():
            return
        s = self.scope
        while s is not None:                                 # dynamic scopes: names may be created by exec/locals() tricks
            if s.dynamic:
                return
            s = s.parent
        extra = " (Python 2 name: it does not exist in Python 3)" if name in PY2 else ""
        self.add("PY-UNDEFINED", "name-error", "high", f"`{name}` is not defined{extra}.{_did_you_mean(name, self._all_visible_names())}", node,
                 fix=f"Define or import `{name}`, or correct the spelling." + (f" Closest name in scope: `{_suggest(name, self._all_visible_names())[0]}`." if _suggest(name, self._all_visible_names()) else ""))

    # -- scoping visitors ---------------------------------------------------------------------------------------------------------------------
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._load(node)

    def _enter(self, kind: str, node: ast.AST) -> Scope:
        sc = Scope(kind, node, self.scope); self.scope = sc; return sc

    def _function(self, node) -> None:
        for d in node.decorator_list:
            self.visit(d)
        a = node.args
        for dflt in a.defaults + [d for d in a.kw_defaults if d is not None]:
            self.visit(dflt)
            if isinstance(dflt, (ast.List, ast.Dict, ast.Set)):
                self.add("PY-MUTDEF", "bug-risk", "medium", "Mutable default argument: the same object is shared by every call.", dflt, fix="Default to `None` and create the list/dict inside the function.")
        self._annotations(node)
        sc = self._enter("function", node)
        for p in a.posonlyargs + a.args + a.kwonlyargs + ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else []):
            sc.bound[p.arg] = p
        body = node.body
        _bind_stmts(body, sc)
        for x in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in ("locals", "vars", "exec", "eval", "globals"):
                sc.dynamic = True
        for g in sc.declared_global:
            self.module.bound.setdefault(g, node)
        self._body_checks(body)
        for st in body:
            self.visit(st)
        self._unused_locals(sc, node)
        self.scope = sc.parent  # type: ignore[assignment]

    def _annotations(self, node) -> None:
        anns = [p.annotation for p in node.args.posonlyargs + node.args.args + node.args.kwonlyargs + ([node.args.vararg] if node.args.vararg else []) + ([node.args.kwarg] if node.args.kwarg else []) if p.annotation]
        if node.returns:
            anns.append(node.returns)
        for an in anns:
            self._annotation(an)

    def _annotation(self, an: ast.AST) -> None:
        if isinstance(an, ast.Constant) and isinstance(an.value, str):
            for nm in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", an.value):
                sc = self._visible(nm)
                if sc is not None:
                    sc.used.add(nm)
            return
        self.suppress += 1 if self.future_annotations else 0
        self.visit(an)
        self.suppress -= 1 if self.future_annotations else 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for dflt in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
            self.visit(dflt)
        sc = self._enter("function", node)
        a = node.args
        for p in a.posonlyargs + a.args + a.kwonlyargs + ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else []):
            sc.bound[p.arg] = p
        self.visit(node.body)
        self.scope = sc.parent  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for d in node.decorator_list:
            self.visit(d)
        for b in node.bases:
            self.visit(b)
        for k in node.keywords:
            self.visit(k.value)
        sc = self._enter("class", node)
        _bind_stmts(node.body, sc)
        self.class_stack.append(node)
        for st in node.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.method_of[st] = node
        self._class_attrs(node)
        self._body_checks(node.body)
        for st in node.body:
            self.visit(st)
        self.class_stack.pop()
        self.scope = sc.parent  # type: ignore[assignment]

    def _comprehension(self, node, elts) -> None:
        gens = node.generators
        self.visit(gens[0].iter)
        sc = self._enter("comprehension", node)
        for g in gens:
            for n in _targets(g.target):
                sc.bound[n.id] = g
        for i, g in enumerate(gens):
            if i:
                self.visit(g.iter)
            for c in g.ifs:
                self.visit(c)
        for e in elts:
            self.visit(e)
        self.scope = sc.parent  # type: ignore[assignment]

    def visit_ListComp(self, n):
        self._comprehension(n, [n.elt])

    visit_SetComp = visit_GeneratorExp = visit_ListComp

    def visit_DictComp(self, n):
        self._comprehension(n, [n.key, n.value])

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._annotation(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self.visit(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        for st in node.body:
            self.visit(st)

    # -- class attributes -------------------------------------------------------------------------------------------------------------------
    def _class_attrs(self, cls: ast.ClassDef) -> None:
        local_classes = {n.name: n for n in self.tree.body if isinstance(n, ast.ClassDef)}
        attrs: set[str] = set(); known = True
        for b in cls.bases:
            if isinstance(b, ast.Name) and b.id == "object":
                continue
            if isinstance(b, ast.Name) and b.id in local_classes and b.id != cls.name:
                other = local_classes[b.id]
                inf = self.class_info.get(other) or self._info_for(other)
                attrs |= inf["attrs"]; known = known and inf["known"]
            else:
                known = False
        inf = self._info_for(cls)
        attrs |= inf["attrs"]; known = known and inf["known"]
        if cls.decorator_list:
            known = False
        self.class_info[cls] = {"attrs": attrs, "known": known}

    def _info_for(self, cls: ast.ClassDef) -> dict:
        attrs: set[str] = set(); known = True
        for st in cls.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                attrs.add(st.name)
            elif isinstance(st, ast.Assign):
                for t in st.targets:
                    for n in _targets(t):
                        attrs.add(n.id)
                    if isinstance(t, ast.Name) and t.id == "__slots__":
                        if isinstance(st.value, (ast.Tuple, ast.List)):
                            attrs |= {e.value for e in st.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                        else:
                            known = False
            elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                attrs.add(st.target.id)
        for x in ast.walk(cls):
            if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)):
                first = x.args.args[0].arg if x.args.args else None
                if first and not any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in x.decorator_list):
                    for y in ast.walk(x):
                        if isinstance(y, ast.Attribute) and isinstance(y.ctx, (ast.Store, ast.Del)) and isinstance(y.value, ast.Name) and y.value.id == first:
                            attrs.add(y.attr)
                        if isinstance(y, ast.Call) and isinstance(y.func, ast.Name) and y.func.id in ("setattr", "vars", "delattr") and y.args and isinstance(y.args[0], ast.Name) and y.args[0].id == first:
                            known = False
                        if isinstance(y, ast.Attribute) and y.attr == "__dict__" and isinstance(y.value, ast.Name) and y.value.id == first:
                            known = False
                if x.name in ("__getattr__", "__getattribute__", "__setattr__"):
                    known = False
        return {"attrs": attrs, "known": known}

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.visit(node.value)
        if not isinstance(node.ctx, ast.Load):
            return
        # self.x typos
        if self.class_stack and isinstance(node.value, ast.Name):
            fn = self._self_method(node.value.id)
            cls = self.method_of.get(fn) if fn is not None else None
            if fn is not None and cls is not None and not any(isinstance(d, ast.Name) and d.id in ("staticmethod", "classmethod") for d in fn.decorator_list):
                info = self.class_info.get(cls)
                if info and info["known"] and node.attr not in info["attrs"] and not (node.attr.startswith("__") and node.attr.endswith("__")):
                    sug = _suggest(node.attr, info["attrs"])
                    self.add("PY-ATTR", "name-error", "high" if sug else "medium", f"`{node.value.id}.{node.attr}` is read but `{node.attr}` is never assigned or defined in class `{cls.name}`.{(' Did you mean `' + sug[0] + '`?') if sug else ''}", node,
                             confidence="high" if sug else "medium", fix=f"Use the attribute that exists{(': `' + sug[0] + '`') if sug else ''}, or assign `{node.value.id}.{node.attr}` in `__init__`.")
        # stdlib module attribute typos
        chain = self._chain(node)
        if chain and chain[0] in self.stdlib_alias and self._visible(chain[0]) is self.module:
            self._check_module_chain(chain, node)

    def _self_method(self, name: str):
        """The method of the current class whose first parameter is `name` (the real `self`), or None when `name` is anything else."""
        sc = self._visible(name)
        if sc is not None and sc.kind == "function" and sc.node in self.method_of and sc.node.args.args and sc.node.args.args[0].arg == name:
            return sc.node
        return None

    def _enclosing_function(self):
        s = self.scope
        while s is not None:
            if s.kind == "function" and isinstance(s.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return s.node
            s = s.parent
        return None

    @staticmethod
    def _chain(node: ast.AST) -> list[str] | None:
        out: list[str] = []
        while isinstance(node, ast.Attribute):
            out.append(node.attr); node = node.value
        if isinstance(node, ast.Name):
            out.append(node.id); return out[::-1]
        return None

    def _check_module_chain(self, chain: list[str], node: ast.Attribute) -> None:
        modname = self.stdlib_alias[chain[0]]
        try:
            obj = importlib.import_module(modname)
        except Exception:
            return
        for i, part in enumerate(chain[1:], 1):
            if not hasattr(obj, part):
                try:                                   # `import os.path` style submodules
                    obj = importlib.import_module(f"{getattr(obj, '__name__', modname)}.{part}")
                    continue
                except Exception:
                    pass
                if i == len(chain) - 1 or True:
                    pool = [a for a in dir(obj) if not a.startswith("_")]
                    sug = _suggest(part, pool)
                    plat = part in PLATFORM_ONLY
                    self.add("PY-MODATTR", "name-error", "high" if not plat else "low", f"module `{getattr(obj, '__name__', chain[0])}` has no attribute `{part}`.{(' Did you mean `' + sug[0] + '`?') if sug else ''}" + (f" (This name exists only on some platforms; this server runs {sys.platform}.)" if plat else ""), node,
                             confidence="high" if not plat else "low", fix=f"Use `{sug[0]}`." if sug else "Check the module's documentation for the correct name.")
                return
            obj = getattr(obj, part)
            if not (isinstance(obj, type(sys)) or isinstance(obj, type)):
                return

    # -- calls ---------------------------------------------------------------------------------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        for k in node.keywords:
            if k.arg:
                self._secret(k.arg, k.value, k.value)
        self._security_call(node)
        self._arity(node)

    def _sig_for(self, node: ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            sc = self._visible(f.id)
            if sc is self.module and f.id in self.local_sigs and isinstance(self.module.bound.get(f.id), (ast.FunctionDef, ast.AsyncFunctionDef)):
                return f.id, self.local_sigs[f.id]
            if sc is self.module and f.id in self.import_binding:
                fpath, orig = self.import_binding[f.id]
                ex = self.project.exports(fpath)
                if ex and orig in ex[1]:
                    return f.id, ex[1][orig]
            if sc is self.module and isinstance(self.module.bound.get(f.id), ast.ClassDef):
                cls = self.module.bound[f.id]
                init = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
                if init and not init.decorator_list and not cls.decorator_list and not cls.bases:
                    return f.id, make_sig(init, drop_first=True)
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and self.class_stack:
            fn = self._self_method(f.value.id)
            if fn is not None and not any(isinstance(d, ast.Name) and d.id in ("staticmethod", "classmethod") for d in fn.decorator_list):
                cls = self.method_of[fn]
                info = self.class_info.get(cls)
                if info and info["known"]:
                    m = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == f.attr]
                    if len(m) == 1 and not m[0].decorator_list:
                        return f"{f.value.id}.{f.attr}", make_sig(m[0], drop_first=True)
        return None

    def _arity(self, node: ast.Call) -> None:
        got = self._sig_for(node)
        if not got:
            return
        name, sig = got
        if any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
            return
        npos = len(node.args)
        kws = [k.arg for k in node.keywords if k.arg]
        pool = sig.params[sig.posonly:] + sig.kwonly
        if npos > len(sig.params) and not sig.varargs:
            self.add("PY-ARITY", "call-error", "high", f"`{name}()` takes {len(sig.params)} positional argument{'s' if len(sig.params) != 1 else ''} but {npos} {'were' if npos != 1 else 'was'} given.", node,
                     fix=f"Pass at most {len(sig.params)} positional argument(s). Signature: {name}({', '.join(sig.params + sig.kwonly)}).")
            return
        for k in kws:
            if k not in sig.params[sig.posonly:] and k not in sig.kwonly and not sig.varkw:
                sug = _suggest(k, pool)
                self.add("PY-ARITY", "call-error", "high", f"`{name}()` got an unexpected keyword argument `{k}`.{(' Did you mean `' + sug[0] + '`?') if sug else ''}", node,
                         fix=f"Valid parameters: {', '.join(sig.params + sig.kwonly) or '(none)'}.")
                return
            if k in sig.params[:npos]:
                self.add("PY-ARITY", "call-error", "high", f"`{name}()` got multiple values for argument `{k}`.", node)
                return
        missing = [p for i, p in enumerate(sig.params[: sig.required]) if i >= npos and p not in kws] + [p for p in sig.kwonly_required if p not in kws]
        if missing:
            self.add("PY-ARITY", "call-error", "high", f"`{name}()` is missing required argument{'s' if len(missing) > 1 else ''}: {', '.join('`' + m + '`' for m in missing)}.", node,
                     fix=f"Signature: {name}({', '.join(sig.params + sig.kwonly)}).")

    def _security_call(self, node: ast.Call) -> None:
        chain = self._chain(node.func) if isinstance(node.func, (ast.Attribute, ast.Name)) else None
        if not chain:
            return
        dotted = ".".join(chain)
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        def true(v): return isinstance(v, ast.Constant) and v.value is True
        if dotted in ("eval", "exec") and node.args and not isinstance(node.args[0], ast.Constant):
            self.add("PY-EVAL", "security", "high", f"`{dotted}()` on dynamic input can execute attacker-controlled code.", node, fix="Use `ast.literal_eval` or a parser; never evaluate untrusted text.")
        elif dotted == "os.system":
            self.add("PY-OSSYSTEM", "security", "medium", "`os.system()` runs a shell command; unescaped input allows command injection.", node, fix="Use `subprocess.run([...], shell=False)` with an argument list.")
        elif dotted.startswith("subprocess.") and true(kw.get("shell")):
            self.add("PY-SHELL", "security", "medium", f"`{dotted}(..., shell=True)` allows shell injection if any part of the command is user-controlled.", node, fix="Pass an argument list and omit `shell=True`.")
        elif dotted in ("pickle.load", "pickle.loads", "cPickle.loads"):
            self.add("PY-PICKLE", "security", "low", "`pickle` can execute arbitrary code when loading untrusted data (fine for files only you write).", node, confidence="medium", fix="Use JSON or another data-only format for anything an outsider can supply.")
        elif dotted == "yaml.load" and "Loader" not in kw and len(node.args) < 2:
            self.add("PY-YAML", "security", "high", "`yaml.load()` without a Loader can construct arbitrary Python objects.", node, fix="Use `yaml.safe_load()`.")
        elif dotted in ("hashlib.md5", "hashlib.sha1"):
            self.add("PY-WEAKHASH", "security", "low", f"`{dotted}` is a weak hash: do not use it for passwords or integrity checks.", node, confidence="medium", fix="Use `hashlib.sha256`, or `bcrypt`/`argon2` for passwords.")
        elif dotted.startswith("requests.") and "verify" in kw and isinstance(kw["verify"], ast.Constant) and kw["verify"].value is False:
            self.add("PY-TLS", "security", "high", "TLS certificate verification is disabled (`verify=False`).", node, fix="Remove `verify=False`; fix the certificate instead.")
        elif chain[-1] == "run" and true(kw.get("debug")):
            self.add("PY-DEBUG", "security", "medium", "`debug=True` exposes an interactive debugger and should never be enabled in production.", node, confidence="medium", fix="Read the debug flag from configuration and default it to False.")
        elif chain[-1] in ("execute", "executemany", "executescript") and node.args:
            a = node.args[0]
            composed = isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute) and a.func.attr == "format" and isinstance(a.func.value, ast.Call) and (self._chain(a.func.value.func) or [""])[-1] in ("SQL", "Composed")
            risky = not composed and isinstance(a, ast.JoinedStr) or (isinstance(a, ast.BinOp) and isinstance(a.op, (ast.Add, ast.Mod)) and not (isinstance(a.left, ast.Constant) and isinstance(a.right, ast.Constant))) or \
                (isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute) and a.func.attr == "format")
            if risky and not composed:
                self.add("PY-SQLI", "security", "medium", "SQL built by string formatting or concatenation: if any part comes from user input this is a SQL-injection risk.", node, confidence="medium", fix="Use parameterized queries: `cursor.execute('... WHERE id = ?', (value,))`.")
        elif dotted == "tempfile.mktemp":
            self.add("PY-MKTEMP", "security", "medium", "`tempfile.mktemp` is racy and insecure.", node, fix="Use `tempfile.mkstemp()` or `NamedTemporaryFile`.")

    # -- hard-coded secrets (assignments and keyword arguments only: never text in comments or docstrings) ------------------------------------------------
    _SECRET_NAME = re.compile(r"(?i)(api[_-]?key|api[_-]?token|secret|passwd|password|private[_-]?key|access[_-]?token|auth[_-]?token|(?:^|[_-])token(?:$|[_-]))")
    _FAKE = re.compile(r"(?i)^(your|<|\$\{|\{\{|%\(|changeme|change[-_ ]me|xxx|\*+$|example|placeholder|todo|dummy|test|fake|sample|secret$|password$|token$|\.\.\.|none$|null$)")

    def _secret(self, name: str, value: ast.AST, node: ast.AST) -> None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and len(value.value) >= 8 and self._SECRET_NAME.search(name) and not self._FAKE.match(value.value) and " " not in value.value.strip() \
                and not re.search(r"(?i)(url|uri|path|file|endpoint|header|prefix|suffix|name|type|field|env|var|dir|host|label|param|scope)$", name) \
                and not re.match(r"(?i)^(https?|ftp|wss?)://[^@\s]*$", value.value):      # a URL without embedded credentials is not a secret
            self.add("SECRET", "security", "high", f"`{name}` looks like a hard-coded secret.", node, confidence="medium", fix="Read it from an environment variable or a secrets manager, and rotate the exposed value.")

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        for t in node.targets:
            nm = t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else t.slice.value if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str) else None
            if nm:
                self._secret(nm, node.value, node)

    # -- expressions / statements pattern rules --------------------------------------------------------------------------------------------
    def visit_Compare(self, node: ast.Compare) -> None:
        self.generic_visit(node)
        left = node.left
        for op, right in zip(node.ops, node.comparators):
            lit = lambda n: isinstance(n, ast.Constant) and n.value is not None and not isinstance(n.value, (bool, type(Ellipsis)))
            if isinstance(op, (ast.Is, ast.IsNot)) and (lit(left) or lit(right)):
                self.add("PY-ISLIT", "bug-risk", "medium", "`is` compared with a literal: this tests identity, not equality, and its result is unreliable.", node, fix="Use `==` / `!=`.")
            if isinstance(op, (ast.Eq, ast.NotEq)) and ((isinstance(right, ast.Constant) and right.value is None) or (isinstance(left, ast.Constant) and left.value is None)):
                self.add("PY-NONECMP", "style", "low", "Comparison to `None` with `==`/`!=`: use `is None` / `is not None`.", node, fix="Use `is` / `is not`.")
            left = right

    def visit_Assert(self, node: ast.Assert) -> None:
        self.generic_visit(node)
        if isinstance(node.test, ast.Tuple) and node.test.elts:
            self.add("PY-ASSERT", "bug-risk", "high", "`assert (condition, \"message\")` asserts a non-empty tuple, which is always true: the check never fails.", node, fix="Write `assert condition, \"message\"` without the parentheses around both.")

    def visit_BinOp(self, node: ast.BinOp) -> None:
        self.generic_visit(node)
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and isinstance(node.right, ast.Constant) and node.right.value == 0 and not isinstance(node.right.value, bool):
            self.add("PY-DIVZERO", "bug-risk", "high", "Division by the literal `0` always raises ZeroDivisionError.", node)
        if isinstance(node.op, ast.Add):
            l, r = node.left, node.right
            if isinstance(l, ast.Constant) and isinstance(r, ast.Constant) and type(l.value) in (str, int, float) and type(r.value) in (str, int, float) and (isinstance(l.value, str) != isinstance(r.value, str)):
                self.add("PY-TYPEMIX", "bug-risk", "high", "Adding a string and a number raises TypeError.", node, fix="Convert the number with `str()` or use an f-string.")
        if isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str) and isinstance(node.right, ast.Tuple):
            n = len(re.findall(r"%(?!%)[#0\- +]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrsa]", node.left.value))
            if not any(isinstance(e, ast.Starred) for e in node.right.elts) and n != len(node.right.elts) and "%(" not in node.left.value:
                self.add("PY-FORMAT", "bug-risk", "high", f"Format string expects {n} value(s) but {len(node.right.elts)} were given.", node, fix="Make the number of `%` placeholders equal the number of values.")

    def visit_Dict(self, node: ast.Dict) -> None:
        self.generic_visit(node)
        seen: dict = {}
        for k in node.keys:
            if isinstance(k, ast.Constant):
                if k.value in seen:
                    self.add("PY-DUPKEY", "bug-risk", "medium", f"Duplicate key {k.value!r} in dict literal: the later value silently wins.", k)
                seen[k.value] = True

    def _body_checks(self, body: list) -> None:
        defs: dict[str, ast.AST] = {}
        for i, st in enumerate(body):
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if st.name in defs and not st.decorator_list and not getattr(defs[st.name], "decorator_list", []):
                    self.add("PY-REDEF", "bug-risk", "medium", f"`{st.name}` is defined twice in the same scope (first at line {defs[st.name].lineno}): the first definition is lost.", st, fix="Rename or remove one of them.")
                defs[st.name] = st
            if isinstance(st, (ast.Return, ast.Raise, ast.Break, ast.Continue)) and i + 1 < len(body):
                nxt = body[i + 1]
                self.add("PY-UNREACHABLE", "bug-risk", "low", f"Unreachable code after `{type(st).__name__.lower()}`.", nxt, confidence="high", fix="Remove it, or move it before the statement that ends the block.")
                break

    def visit_FunctionDefChecks(self, node) -> None:  # pragma: no cover (kept for clarity)
        pass

    def visit_Try(self, node: ast.Try) -> None:
        for h in node.handlers:
            if h.type is None:
                self.add("PY-BAREEXCEPT", "bug-risk", "medium", "Bare `except:` also catches KeyboardInterrupt and SystemExit and hides real errors.", h, fix="Catch the specific exceptions you expect.")
            if len(h.body) == 1 and isinstance(h.body[0], ast.Pass):
                broad = h.type is None or (isinstance(h.type, ast.Name) and h.type.id in ("Exception", "BaseException"))
                self.add("PY-SWALLOW", "bug-risk", "medium" if broad else "low", "The exception is caught and silently ignored (`pass`): failures will go unnoticed.", h, fix="Handle it, log it, or let it propagate.")
        self.generic_visit(node)

    def _method_checks(self, cls: ast.ClassDef) -> None:
        for st in cls.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                deco = {d.id for d in st.decorator_list if isinstance(d, ast.Name)}
                if not st.args.args and not st.args.vararg and not (deco & {"staticmethod"}) and not st.args.posonlyargs:
                    self.add("PY-NOSELF", "call-error", "high", f"Method `{st.name}` has no `self` parameter: calling it on an instance raises TypeError.", st, fix="Add `self` as the first parameter (or mark it `@staticmethod`).")

    # defaults
    def visit_arguments(self, node: ast.arguments) -> None:
        for d in node.defaults + [x for x in node.kw_defaults if x is not None]:
            if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                self.add("PY-MUTDEF", "bug-risk", "medium", "Mutable default argument: the same object is shared by every call.", d, fix="Default to `None` and create the list/dict inside the function.")
        self.generic_visit(node)

    # -- unused -------------------------------------------------------------------------------------------------------------------------------
    def _unused_locals(self, sc: Scope, fn) -> None:
        if sc.dynamic or sc.declared_global or sc.declared_nonlocal:
            return
        for name, st in sc.bound.items():
            if name in sc.used or name.startswith("_") or name in ("self", "cls"):
                continue
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                self.add("PY-UNUSEDVAR", "unused", "low", f"Local variable `{name}` is assigned but never used.", st.targets[0], fix="Remove it, or use it (a misspelled later use would show up as an undefined name).")
            elif isinstance(st, ast.ExceptHandler):
                self.add("PY-UNUSEDVAR", "unused", "low", f"Exception variable `{name}` is never used.", st, fix="Drop `as " + name + "`.")

    def finish(self) -> None:
        self._body_checks(self.tree.body)
        for cls in [n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)]:
            self._method_checks(cls)
        if not self.path.endswith("__init__.py"):
            for nm, st, alias in self.imports:
                if nm not in self.module.used and nm not in self.all_names and not (isinstance(st, ast.ImportFrom) and alias.asname == alias.name):
                    if self.module.dynamic or self.module.star:
                        continue
                    shown = alias.name if isinstance(st, ast.Import) else f"{st.module or '.'}.{alias.name}"
                    self.add("PY-UNUSEDIMPORT", "unused", "low", f"`{shown}` is imported but never used.", st, confidence="high", fix="Remove the import (or use it).")
        for st in self.tree.body:      # project imports that do not exist
            if isinstance(st, ast.ImportFrom):
                self._check_project_import(st)
            elif isinstance(st, ast.Import):
                for a in st.names:
                    top = a.name.split(".")[0]
                    if top in self.project.tops and a.name not in self.project.mod_to_file and not any(m.startswith(a.name + ".") for m in self.project.mod_to_file):
                        pool = self.project.submodules(a.name.rsplit(".", 1)[0]) if "." in a.name else self.project.tops
                        sug = _suggest(a.name.rsplit(".", 1)[-1], pool)
                        self.add("PY-IMPORT", "import-error", "high", f"Module `{a.name}` does not exist in this project.{(' Did you mean `' + (a.name.rsplit('.', 1)[0] + '.' if '.' in a.name else '') + sug[0] + '`?') if sug else ''}", st)

    def _check_project_import(self, st: ast.ImportFrom) -> None:
        mod = self.project.resolve_from(self.path, st.module, st.level)
        if mod is None or mod == "":              # `from . import x` at the project root: the package context is outside the reviewed folder
            return
        top = mod.split(".")[0] if mod else ""
        f = self.project.module_file(mod)
        if mod and not f and not self.project.is_package(mod):
            if top in self.project.tops and st.level == 0:
                parent = mod.rsplit(".", 1)[0] if "." in mod else ""
                pool = self.project.submodules(parent) if parent else self.project.tops
                sug = _suggest(mod.rsplit(".", 1)[-1], pool)
                self.add("PY-IMPORT", "import-error", "high", f"Module `{mod}` does not exist in this project.{(' Did you mean `' + (parent + '.' if parent else '') + sug[0] + '`?') if sug else ''}", st,
                         fix="Fix the module path.")
            return
        if not f and mod in {m for m in self.project.mod_to_file}:
            f = self.project.mod_to_file[mod]
        names_here = self.project.exports(f) if f else None
        subs = self.project.submodules(mod) if mod else set()
        for a in st.names:
            if a.name == "*":
                continue
            if f and names_here is not None:
                names, _, open_ = names_here
                if a.name not in names and a.name not in subs and not open_:
                    sug = _suggest(a.name, names | subs)
                    self.add("PY-IMPORT", "import-error", "high", f"Cannot import `{a.name}` from `{mod or '.'}`: it is not defined there.{(' Did you mean `' + sug[0] + '`?') if sug else ''}", st,
                             fix=f"`{f}` defines: {', '.join(sorted(n for n in names if not n.startswith('_'))[:10]) or '(nothing public)'}.")
            elif not f and a.name not in subs:
                sug = _suggest(a.name, subs)
                self.add("PY-IMPORT", "import-error", "high", f"Cannot import `{a.name}` from package `{mod or '.'}`.{(' Did you mean `' + sug[0] + '`?') if sug else ''}", st)


def check_python(path: str, text: str, project: Project) -> list[Finding]:
    out: list[Finding] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            compile(text, path, "exec", dont_inherit=True)
        except SyntaxError as e:
            return [Finding("PY-SYNTAX", "syntax", "high", f"{e.msg}" if e.msg else "Invalid syntax", e.lineno or 1, max(0, (e.offset or 1) - 1), (e.end_offset or 0) and max(0, e.end_offset - 1),
                            fix="Fix the syntax error: " + _syntax_hint(e))]
        except (ValueError, RecursionError, MemoryError) as e:
            return [Finding("PY-SYNTAX", "syntax", "high", f"Cannot compile: {e}", 1)]
    for w in caught:
        if "assertion is always true" in str(w.message):            # reported with more detail by PY-ASSERT
            continue
        if issubclass(w.category, SyntaxWarning) or ("escape" in str(w.message).lower() and issubclass(w.category, DeprecationWarning)):
            out.append(Finding("PY-WARN", "bug-risk", "medium", str(w.message), getattr(w, "lineno", 1) or 1, 0, confidence="high", fix="Use a raw string (r\"...\") or escape the backslash."))
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return out
    ck = Checker(path, text, tree, project)
    ck.visit(tree)
    ck.finish()
    return out + ck.out


def _syntax_hint(e: SyntaxError) -> str:
    m = (e.msg or "").lower()
    if "never closed" in m or "unmatched" in m or "closing parenthesis" in m:
        return "a bracket, brace or parenthesis is missing or extra: check the line above as well."
    if "expected ':'" in m:
        return "add the missing colon at the end of the statement."
    if "indent" in m:
        return "make the indentation consistent (use 4 spaces, no tabs mixed in)."
    if "unterminated string" in m or "eol while scanning" in m:
        return "close the string with a matching quote."
    if "invalid syntax" in m:
        return "check for a misspelled keyword (`retrun`, `esle`, `improt`), a missing operator or comma, or an unclosed bracket on the previous line."
    return "see the message above."
