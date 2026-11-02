"""Per-language Tree-sitter extractors: functions, classes, methods, interfaces, imports, variables, APIs, tests, models."""
from __future__ import annotations
import re

from .model import ApiRoute, ImportRef
from .ts_core import Visitor, norm_callee

HTTP_WORDS = {"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE", "patch": "PATCH", "head": "HEAD", "options": "OPTIONS", "all": "ANY"}
FUNC_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}


def join_path(prefix: str, path: str) -> str:
    return ("/" + "/".join(x.strip("/") for x in (prefix, path) if x.strip("/"))) if (prefix or path) else ""


def strip_generics(s: str) -> str:
    while True:
        t = re.sub(r"<[^<>]*>", "", s)
        if t == s:
            return s.strip()
        s = t


# ======================================================================================================
class JsVisitor(Visitor):
    """JavaScript, TypeScript and TSX."""

    language = "javascript"
    call_types = ("call_expression", "new_expression")
    ROUTER = re.compile(r"^(app|router|route|routes|server|fastify|koa|[A-Za-z]*Router|[A-Za-z]*router|[A-Za-z]*App)$")
    TEST_FUNCS = {"describe", "suite", "context", "it", "test", "specify"}

    def callee(self, n) -> str:
        if n.type == "call_expression":
            return self.t(self.fld(n, "function"))
        if n.type == "new_expression":
            return self.t(self.fld(n, "constructor"))
        return ""

    def run(self) -> None:
        for ch in self.root.named_children:
            self.visit(ch)
        self.api_pass()
        self.test_pass()

    # ---- declarations ------------------------------------------------------------------------
    def visit(self, n, exported: bool = False, wrapper=None, decorators: list[str] | None = None) -> None:
        ty, outer = n.type, wrapper or n
        if ty == "export_statement":
            src = self.fld(n, "source")
            if src is not None:
                self.facts.imports.append(ImportRef(module=self.string_value(src), line=n.start_point[0] + 1, kind="reexport"))
            decl = self.fld(n, "declaration")
            if decl is not None:
                decos = [self.t(c) for c in n.children if c.type == "decorator"]
                self.visit(decl, True, n, decos)
        elif ty == "import_statement":
            self.import_stmt(n)
        elif ty in ("function_declaration", "generator_function_declaration"):
            self.function(n, outer, exported)
        elif ty in ("class_declaration", "abstract_class_declaration", "class"):
            self.klass(n, outer, exported, decorators or [])
        elif ty == "interface_declaration":
            name = self.t(self.fld(n, "name"))
            bases = [strip_generics(self.t(c)) for c in n.children if c.type == "extends_type_clause" for c in c.named_children if c.type != "type_arguments"]
            doc, _ = self.leading(outer)
            self.add("interface", name, name, outer, signature=self.signature(n), doc=doc, bases=bases, exported=exported)
        elif ty == "type_alias_declaration":
            name = self.t(self.fld(n, "name"))
            self.add("type", name, name, outer, signature=" ".join(self.t(n).split())[:160], doc=self.leading(outer)[0], exported=exported)
        elif ty == "enum_declaration":
            name = self.t(self.fld(n, "name"))
            self.add("enum", name, name, outer, signature=f"enum {name}", doc=self.leading(outer)[0], exported=exported)
        elif ty in ("lexical_declaration", "variable_declaration"):
            self.variables(n, outer, exported)
        elif ty in ("internal_module", "module", "ambient_declaration"):
            for ch in n.named_children:
                if ch.type in ("statement_block",):
                    for s in ch.named_children:
                        self.visit(s, exported)
                else:
                    self.visit(ch, exported)

    def import_stmt(self, n) -> None:
        src = self.fld(n, "source")
        if src is None:
            return
        ref = ImportRef(module=self.string_value(src), line=n.start_point[0] + 1)
        for ch in n.named_children:
            if ch.type != "import_clause":
                continue
            for c in ch.named_children:
                if c.type == "identifier":
                    ref.names.append(["default", self.t(c)])
                elif c.type == "namespace_import":
                    ref.alias = self.t(c.named_children[0]) if c.named_children else ""
                elif c.type == "named_imports":
                    for sp in c.named_children:
                        if sp.type == "import_specifier":
                            name, alias = self.fld(sp, "name"), self.fld(sp, "alias")
                            ref.names.append([self.t(name), self.t(alias) if alias is not None else ""])
        self.facts.imports.append(ref)

    def function(self, n, outer, exported: bool) -> None:
        name = self.t(self.fld(n, "name"))
        if not name:
            return
        tags = ["async"] if any(c.type == "async" for c in n.children) else []
        self.add("function", name, name, outer, signature=self.signature(n), doc=self.leading(outer)[0], calls=self.calls(self.fld(n, "body") or n),
                 tags=tags, exported=exported)

    def klass(self, n, outer, exported: bool, decorators: list[str]) -> None:
        name = self.t(self.fld(n, "name"))
        if not name:
            return
        bases: list[str] = []
        for ch in n.children:
            if ch.type != "class_heritage":
                continue
            for sub in ch.named_children:
                if sub.type == "extends_clause":
                    bases += [strip_generics(self.t(v)) for v in sub.children_by_field_name("value")]
                elif sub.type == "implements_clause":
                    bases += [strip_generics(self.t(v)) for v in sub.named_children if v.type != "type_arguments"]
                else:
                    bases.append(strip_generics(self.t(sub)))
        decos = decorators + [self.t(c) for c in n.children if c.type == "decorator"]
        tags, extra, prefix = [], {}, ""
        for d in decos:
            dn = re.match(r"@(\w+)", d)
            if not dn:
                continue
            if dn.group(1) in ("Entity", "Schema", "Table", "Model"):
                tags.append("model"); extra = {"framework": "typeorm/nest", "fields": []}
            if dn.group(1) in ("Controller", "RestController"):
                m = re.search(r"[\"'`]([^\"'`]*)[\"'`]", d)
                prefix = m.group(1) if m else ""
        if n.type == "abstract_class_declaration":
            tags.append("abstract")
        cls = self.add("class", name, name, outer, signature=self.signature(n), doc=self.leading(outer)[0], bases=bases, tags=tags,
                       decorators=[d[:80] for d in decos], exported=exported, extra=extra)
        body = self.fld(n, "body")
        if body is None:
            return
        pending: list[str] = []
        for m in body.named_children:
            if m.type == "decorator":
                pending.append(self.t(m)); continue
            mdecos = pending + [self.t(c) for c in m.children if c.type == "decorator"]
            pending = []
            if m.type in ("method_definition", "abstract_method_signature", "method_signature"):
                self.method(m, name, mdecos, prefix, exported)
            elif m.type in ("public_field_definition", "field_definition"):
                fname = self.fld(m, "name") or self.fld(m, "property")
                val = self.fld(m, "value")
                if fname is not None and val is not None and val.type in FUNC_VALUES:
                    self.add("method", self.t(fname), f"{name}.{self.t(fname)}", m, name, signature=" ".join(self.t(m).split())[:160],
                             calls=self.calls(val), exported=exported, decorators=mdecos)
                elif fname is not None and "model" in tags:
                    cls.extra.setdefault("fields", []).append(self.t(fname))

    def method(self, m, cls: str, decos: list[str], prefix: str, exported: bool) -> None:
        nm = self.fld(m, "name")
        if nm is None:
            return
        name = self.t(nm)
        qual = f"{cls}.{name}"
        tags, route = [], ""
        for d in decos:
            dm = re.match(r"@(Get|Post|Put|Delete|Patch|All|Options|Head)\b", d)
            if dm:
                pm = re.search(r"[\"'`]([^\"'`]*)[\"'`]", d)
                path = join_path(prefix, pm.group(1) if pm else "")
                method = HTTP_WORDS[dm.group(1).lower()]
                route = f"{method} {path or '/'}"
                tags.append("api")
                self.facts.apis.append(ApiRoute(method, path or "/", qual, m.start_point[0] + 1, "nestjs"))
        self.add("method", name, qual, m, cls, signature=self.signature(m), doc=self.leading(m)[0], calls=self.calls(self.fld(m, "body") or m),
                 decorators=[d[:80] for d in decos], tags=tags, route=route, exported=exported)

    def variables(self, n, outer, exported: bool) -> None:
        is_const = self.t(n).lstrip().startswith("const")
        for d in n.named_children:
            if d.type != "variable_declarator":
                continue
            nm, val = self.fld(d, "name"), self.fld(d, "value")
            if nm is None or nm.type != "identifier":
                continue
            name = self.t(nm)
            if val is not None and val.type in FUNC_VALUES:
                tags = ["async"] if any(c.type == "async" for c in val.children) else []
                self.add("function", name, name, outer, signature=" ".join(self.t(n).split("=>")[0].split())[:200], doc=self.leading(outer)[0],
                         calls=self.calls(self.fld(val, "body") or val), tags=tags, exported=exported)
                continue
            if val is not None and val.type == "call_expression":
                fn = self.t(self.fld(val, "function"))
                args = self.fld(val, "arguments")
                first = args.named_children[0] if args is not None and args.named_children else None
                if fn == "require" and first is not None and first.type == "string":
                    self.facts.imports.append(ImportRef(module=self.string_value(first), alias=name, line=n.start_point[0] + 1, kind="require"))
                    continue
                if re.search(r"(^|\.)(model|define)$", fn) and first is not None and first.type == "string":
                    self.add("variable", name, name, outer, tags=["model"], extra={"framework": "mongoose/sequelize", "fields": []},
                             signature=" ".join(self.t(n).split())[:120], exported=exported)
                    continue
            if val is not None and val.type == "new_expression" and "Schema" in self.t(self.fld(val, "constructor")):
                self.add("variable", name, name, outer, tags=["model"], extra={"framework": "mongoose", "fields": []},
                         signature=" ".join(self.t(n).split())[:120], exported=exported)
                continue
            self.add("constant" if is_const else "variable", name, name, outer, signature=" ".join(self.t(n).split())[:120], exported=exported)

    # ---- whole-file passes ---------------------------------------------------------------------
    def api_pass(self) -> None:
        for n in self.walk(self.root, {"call_expression"}):
            fn = self.fld(n, "function")
            if fn is None or fn.type != "member_expression":
                continue
            prop = self.t(self.fld(fn, "property"))
            obj = self.t(self.fld(fn, "object")).split(".")[-1]
            args = self.fld(n, "arguments")
            if prop not in HTTP_WORDS or not self.ROUTER.match(obj) or args is None or len(args.named_children) < 2:
                continue
            first, rest = args.named_children[0], args.named_children[1:]
            if first.type not in ("string", "template_string"):
                continue
            path = self.string_value(first)
            if not path.startswith(("/", "*")):
                continue
            method = HTTP_WORDS[prop]
            handler = ""
            for a in rest:
                if a.type in FUNC_VALUES:
                    name = f"{method} {path}"
                    self.add("function", name, name, n, signature=name, calls=self.calls(self.fld(a, "body") or a), tags=["api", "inline"], route=name)
                    handler = name
                elif a.type in ("identifier", "member_expression"):
                    handler = self.t(a).split(".")[-1]
            if handler:
                self.facts.apis.append(ApiRoute(method, path, handler, n.start_point[0] + 1, "express"))

    def test_pass(self) -> None:
        for n in self.walk(self.root, {"call_expression"}):
            fn = self.t(self.fld(n, "function")).split(".")[0]
            if fn not in self.TEST_FUNCS:
                continue
            self.facts.is_test = True
            args = self.fld(n, "arguments")
            first = args.named_children[0] if args is not None and args.named_children else None
            if fn in ("it", "test", "specify") and first is not None and first.type in ("string", "template_string"):
                self.facts.tests.append({"name": self.string_value(first), "line": n.start_point[0] + 1})


class TsVisitor(JsVisitor):
    language = "typescript"


# ======================================================================================================
class JavaVisitor(Visitor):
    language = "java"
    call_types = ("method_invocation", "object_creation_expression")
    TYPES = {"class_declaration": "class", "interface_declaration": "interface", "enum_declaration": "enum",
             "record_declaration": "class", "annotation_type_declaration": "interface"}
    SPRING = {"GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT", "DeleteMapping": "DELETE", "PatchMapping": "PATCH",
              "RequestMapping": "ANY"}
    JAXRS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"}

    def callee(self, n) -> str:
        if n.type == "method_invocation":
            obj, name = self.fld(n, "object"), self.t(self.fld(n, "name"))
            return f"{self.t(obj)}.{name}" if obj is not None else name
        if n.type == "object_creation_expression":
            return self.t(self.fld(n, "type"))
        return ""

    def run(self) -> None:
        for ch in self.root.named_children:
            if ch.type == "package_declaration":
                self.facts.package = self.t(ch.named_children[0]) if ch.named_children else ""
            elif ch.type == "import_declaration":
                path = next((self.t(c) for c in ch.named_children if c.type == "scoped_identifier"), "")
                star = any(c.type == "asterisk" for c in ch.children)
                self.facts.imports.append(ImportRef(module=path, names=[["*", ""]] if star else [], line=ch.start_point[0] + 1))
            elif ch.type in self.TYPES:
                self.type_decl(ch, "")

    def mods(self, n) -> tuple[list[str], list[tuple[str, str]]]:
        """(modifier keywords, [(annotation name, raw text)])."""
        m = next((c for c in n.children if c.type == "modifiers"), None)
        words, anns = [], []
        if m is not None:
            for c in m.children:
                if c.type in ("marker_annotation", "annotation"):
                    anns.append((self.t(self.fld(c, "name")), self.t(c)))
                else:
                    words.append(self.t(c))
        return words, anns

    @staticmethod
    def ann_path(raw: str) -> str:
        m = re.search(r"\"([^\"]*)\"", raw)
        return m.group(1) if m else ""

    def type_decl(self, n, prefix: str) -> None:
        name = self.t(self.fld(n, "name"))
        qual = f"{prefix}{name}"
        words, anns = self.mods(n)
        kind = self.TYPES[n.type]
        bases: list[str] = []
        for ch in n.children:
            if ch.type in ("superclass", "super_interfaces", "extends_interfaces"):
                for x in ch.named_children:
                    for t in (x.named_children if x.type == "type_list" else [x]):
                        bases.append(strip_generics(self.t(t)))
        bases = list(dict.fromkeys(b for b in bases if b))
        tags, extra, cprefix = [], {}, ""
        for an, raw in anns:
            if an in ("Entity", "Table", "MappedSuperclass", "Embeddable", "Document"):
                tags.append("model"); extra = {"framework": "jpa", "fields": []}
            if an in ("RequestMapping", "Path"):
                cprefix = self.ann_path(raw)
        if n.type == "record_declaration":
            tags.append("record")
        cls = self.add(kind, name, qual, n, prefix.rstrip(".") if prefix else "", signature=self.signature(n), doc=self.leading(n)[0], bases=bases,
                       tags=tags, decorators=[r[:80] for _, r in anns], exported="public" in words, extra=extra)
        body = self.fld(n, "body")
        if body is not None:
            self.members(body, qual, cprefix, cls)

    def members(self, body, qual: str, cprefix: str, cls) -> None:
        for m in body.named_children:
            if m.type == "enum_body_declarations":
                self.members(m, qual, cprefix, cls)
            elif m.type in self.TYPES:
                self.type_decl(m, f"{qual}.")
            elif m.type in ("method_declaration", "constructor_declaration"):
                self.method(m, qual, cprefix)
            elif m.type == "field_declaration":
                words, _ = self.mods(m)
                for d in self.walk(m, {"variable_declarator"}):
                    nm = self.t(self.fld(d, "name"))
                    const = "static" in words and "final" in words
                    if "model" in cls.tags:
                        cls.extra.setdefault("fields", []).append(nm)
                    self.add("constant" if const else "variable", nm, f"{qual}.{nm}", m, qual, signature=" ".join(self.t(m).split())[:140],
                             exported="public" in words)

    def method(self, m, qual: str, cprefix: str) -> None:
        name = self.t(self.fld(m, "name"))
        words, anns = self.mods(m)
        tags, route, mfq = [], "", f"{qual}.{name}"
        names = {a for a, _ in anns}
        for an, raw in anns:
            if an in self.SPRING:
                method = self.SPRING[an]
                if an == "RequestMapping":
                    mm = re.search(r"RequestMethod\.(\w+)", raw)
                    method = mm.group(1) if mm else "ANY"
                path = join_path(cprefix, self.ann_path(raw))
                route = f"{method} {path or '/'}"; tags.append("api")
                self.facts.apis.append(ApiRoute(method, path or "/", mfq, m.start_point[0] + 1, "spring"))
        jax = names & self.JAXRS
        if jax and "api" not in tags:
            path = join_path(cprefix, next((self.ann_path(r) for a, r in anns if a == "Path"), ""))
            route = f"{sorted(jax)[0]} {path or '/'}"; tags.append("api")
            self.facts.apis.append(ApiRoute(sorted(jax)[0], path or "/", mfq, m.start_point[0] + 1, "jax-rs"))
        if names & {"Test", "ParameterizedTest", "RepeatedTest"}:
            tags.append("test"); self.facts.is_test = True
            self.facts.tests.append({"name": mfq, "line": m.start_point[0] + 1})
        self.add("method", name, mfq, m, qual, signature=self.signature(m), doc=self.leading(m)[0], calls=self.calls(self.fld(m, "body") or m),
                 decorators=[r[:80] for _, r in anns], tags=tags, route=route, exported="public" in words)


# ======================================================================================================
class CVisitor(Visitor):
    language = "c"
    TEST_MACROS = {"TEST", "TEST_F", "TEST_P", "TEST_CASE", "BOOST_AUTO_TEST_CASE", "BOOST_AUTO_TEST_CASE_TEMPLATE", "SCENARIO"}

    def run(self) -> None:
        self.top(self.root, "")

    def top(self, node, scope: str) -> None:
        for ch in node.named_children:
            ty = ch.type
            if ty == "preproc_include":
                p = self.fld(ch, "path")
                text = self.t(p)
                local = p is not None and p.type == "string_literal"
                self.facts.imports.append(ImportRef(module=text.strip('"<>'), level=1 if local else 0, line=ch.start_point[0] + 1))
            elif ty in ("preproc_def", "preproc_function_def"):
                nm = self.t(self.fld(ch, "name"))
                if nm and not nm.startswith("_") and len(self.facts.symbols) < 400:
                    self.add("macro", nm, nm, ch, signature=" ".join(self.t(ch).split())[:140])
            elif ty == "function_definition":
                self.function(ch, scope)
            elif ty in ("struct_specifier", "union_specifier", "class_specifier"):
                self.record(ch, scope)
            elif ty == "enum_specifier":
                nm = self.t(self.fld(ch, "name"))
                if nm and self.fld(ch, "body") is not None:
                    self.add("enum", nm, f"{scope}{nm}", ch, doc=self.leading(ch)[0], signature=f"enum {nm}", exported=True)
            elif ty == "type_definition":
                inner = self.fld(ch, "type")
                alias = self.t(self.fld(ch, "declarator"))
                if inner is not None and inner.type in ("struct_specifier", "union_specifier", "enum_specifier") and self.fld(inner, "body") is not None:
                    if self.t(self.fld(inner, "name")):
                        self.top_one(inner, scope)
                    elif alias:
                        self.add("enum" if inner.type == "enum_specifier" else "struct", alias, f"{scope}{alias}", ch,
                                 doc=self.leading(ch)[0], signature=f"typedef {inner.type.split('_')[0]} {alias}", exported=True)
            elif ty == "declaration":
                self.declaration(ch, scope)
            elif ty in ("namespace_definition",):
                nm = self.t(self.fld(ch, "name"))
                body = self.fld(ch, "body")
                if body is not None:
                    self.top(body, f"{scope}{nm}." if nm else scope)
            elif ty in ("template_declaration", "linkage_specification") or ty.startswith("preproc_"):
                self.top(ch, scope)

    def top_one(self, node, scope: str) -> None:
        class _W:  # tiny shim: process a single node as if it were a child list
            named_children = [node]
        self.top(_W, scope)

    def declarator_node(self, d):
        while d is not None and d.type in ("pointer_declarator", "reference_declarator", "parenthesized_declarator", "array_declarator", "init_declarator", "attributed_declarator"):
            d = self.fld(d, "declarator") or (d.named_children[0] if d.named_children else None)
        if d is not None and d.type == "function_declarator":
            return self.declarator_node(self.fld(d, "declarator"))
        return d

    def function(self, n, scope: str, cls: str = "") -> None:
        dn = self.declarator_node(self.fld(n, "declarator"))
        if dn is None:
            return
        parts = norm_callee(self.t(dn)).split(".") if self.t(dn) else []
        name = (parts[-1] if parts else "").lstrip("?.")
        if not name:
            return
        owner = ".".join(parts[:-1]) if len(parts) > 1 else cls
        qual = f"{scope}{owner}.{name}" if owner else f"{scope}{name}"
        static = any(c.type == "storage_class_specifier" and self.t(c) == "static" for c in n.children)
        if name in self.TEST_MACROS:
            params = self.fld(self.fld(n, "declarator"), "parameters")
            label = ".".join(self.t(p).strip() for p in (params.named_children if params is not None else []))
            self.facts.tests.append({"name": label or name, "line": n.start_point[0] + 1})
            self.facts.is_test = True
            return
        self.add("method" if owner else "function", name, qual, n, f"{scope}{owner}" if owner else "", signature=self.signature(n),
                 doc=self.leading(n)[0], calls=self.calls(self.fld(n, "body") or n), exported=not static)

    def record(self, n, scope: str) -> None:
        nm = self.t(self.fld(n, "name"))
        body = self.fld(n, "body")
        if not nm or body is None:
            return
        qual = f"{scope}{nm}"
        bases = [strip_generics(self.t(c)) for b in n.children if b.type == "base_class_clause" for c in b.named_children if c.type in ("type_identifier", "qualified_identifier", "template_type")]
        kind = "class" if n.type == "class_specifier" else "struct"
        self.add(kind, nm, qual, n, signature=self.signature(n), doc=self.leading(n)[0], bases=bases, exported=True)
        for m in body.named_children:
            if m.type == "function_definition":
                self.function(m, scope, nm)
            elif m.type in ("struct_specifier", "class_specifier", "union_specifier"):
                self.record(m, f"{qual}.")
            elif m.type == "template_declaration":
                for t in m.named_children:
                    if t.type == "function_definition":
                        self.function(t, scope, nm)

    def declaration(self, n, scope: str) -> None:
        if scope and False:
            return
        for d in n.named_children:
            if d.type == "init_declarator":
                dn = self.declarator_node(d)
                if dn is not None and dn.type == "identifier" and len(self.facts.symbols) < 400:
                    name = self.t(dn)
                    const = any(c.type == "type_qualifier" and self.t(c) == "const" for c in n.children)
                    self.add("constant" if const else "variable", name, f"{scope}{name}", n, signature=" ".join(self.t(n).split())[:120])


class CppVisitor(CVisitor):
    language = "cpp"
    call_types = ("call_expression", "new_expression")

    def callee(self, n) -> str:
        if n.type == "new_expression":
            return self.t(self.fld(n, "type"))
        return super().callee(n)


# ======================================================================================================
class GoVisitor(Visitor):
    language = "go"
    ROUTE_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "Get", "Post", "Put", "Delete", "Patch", "Head", "Handle", "HandleFunc", "Any"}

    def run(self) -> None:
        is_test_file = self.path.endswith("_test.go")
        for ch in self.root.named_children:
            ty = ch.type
            if ty == "package_clause":
                self.facts.package = self.t(ch.named_children[0]) if ch.named_children else ""
            elif ty == "import_declaration":
                for spec in self.walk(ch, {"import_spec"}):
                    p = self.fld(spec, "path")
                    nm = self.fld(spec, "name")
                    if p is not None:
                        self.facts.imports.append(ImportRef(module=self.string_value(p), alias=self.t(nm) if nm is not None else "", line=spec.start_point[0] + 1))
            elif ty == "function_declaration":
                name = self.t(self.fld(ch, "name"))
                tags = []
                if is_test_file and re.match(r"(Test|Benchmark|Example|Fuzz)[A-Z_0-9]", name):
                    tags.append("test"); self.facts.tests.append({"name": name, "line": ch.start_point[0] + 1}); self.facts.is_test = True
                self.add("function", name, name, ch, signature=self.signature(ch), doc=self.leading(ch)[0],
                         calls=self.calls(self.fld(ch, "body") or ch), tags=tags, exported=name[:1].isupper())
            elif ty == "method_declaration":
                name = self.t(self.fld(ch, "name"))
                recv = self.fld(ch, "receiver")
                rtype = ""
                if recv is not None:
                    m = re.search(r"\*?\s*([A-Za-z_]\w*)\s*(\[|\)|$)", self.t(recv).strip("()").split()[-1] if self.t(recv).strip("()").split() else "")
                    rtype = m.group(1) if m else ""
                    if not rtype:
                        ids = [self.t(x) for x in self.walk(recv, {"type_identifier"})]
                        rtype = ids[0] if ids else ""
                qual = f"{rtype}.{name}" if rtype else name
                self.add("method", name, qual, ch, rtype, signature=self.signature(ch), doc=self.leading(ch)[0],
                         calls=self.calls(self.fld(ch, "body") or ch), exported=name[:1].isupper())
            elif ty == "type_declaration":
                for spec in ch.named_children:
                    if spec.type != "type_spec":
                        continue
                    name = self.t(self.fld(spec, "name"))
                    inner = self.fld(spec, "type")
                    kind = "struct" if inner is not None and inner.type == "struct_type" else "interface" if inner is not None and inner.type == "interface_type" else "type"
                    tags, extra, bases = [], {}, []
                    if kind == "struct":
                        text = self.t(inner)
                        if "gorm:\"" in text or "gorm.Model" in text:
                            tags.append("model"); extra = {"framework": "gorm", "fields": re.findall(r"^\s*(\w+)\s+\S+\s+`", text, re.M)[:40]}
                        for fd in self.walk(inner, {"field_declaration"}):  # embedded types = composition ("inherits")
                            if self.fld(fd, "name") is None:
                                bases.append(strip_generics(self.t(self.fld(fd, "type"))).lstrip("*"))
                    self.add(kind, name, name, ch if len(ch.named_children) == 1 else spec, doc=self.leading(ch)[0],
                             signature=f"type {name} {kind if kind != 'type' else self.t(inner)[:40]}", tags=tags, extra=extra, bases=bases, exported=name[:1].isupper())
            elif ty in ("const_declaration", "var_declaration"):
                for spec in self.walk(ch, {"const_spec", "var_spec"}):
                    for nm in spec.children_by_field_name("name"):
                        name = self.t(nm)
                        self.add("constant" if ty == "const_declaration" else "variable", name, name, spec, signature=" ".join(self.t(spec).split())[:120],
                                 exported=name[:1].isupper())
        self.api_pass()

    def api_pass(self) -> None:
        for n in self.walk(self.root, {"call_expression"}):
            fn = self.fld(n, "function")
            if fn is None or fn.type != "selector_expression":
                continue
            field = self.t(self.fld(fn, "field"))
            args = self.fld(n, "arguments")
            if field not in self.ROUTE_METHODS or args is None or not args.named_children:
                continue
            first = args.named_children[0]
            if first.type not in ("interpreted_string_literal", "raw_string_literal"):
                continue
            path = self.string_value(first)
            if not path.startswith("/"):
                continue
            method = "ANY" if field in ("Handle", "HandleFunc", "Any") else field.upper()
            last = args.named_children[-1]
            handler = self.t(last).split(".")[-1] if last.type in ("identifier", "selector_expression") else ""
            self.facts.apis.append(ApiRoute(method, path, handler, n.start_point[0] + 1, "go-http"))


# ======================================================================================================
class RustVisitor(Visitor):
    language = "rust"
    ROUTE_ATTR = re.compile(r"#\[\s*(get|post|put|delete|patch|head|options)\s*\(\s*\"([^\"]*)\"")
    MODEL_DERIVES = {"Queryable", "Insertable", "FromRow", "DeriveEntityModel", "Model", "Identifiable", "AsChangeset"}

    def run(self) -> None:
        self.items(self.root, "", False)
        self.api_pass()

    def use_decl(self, n) -> None:
        arg = self.fld(n, "argument")
        if arg is None:
            return
        line = n.start_point[0] + 1
        if arg.type == "scoped_use_list":
            base = self.t(self.fld(arg, "path"))
            names = []
            for c in self.fld(arg, "list").named_children:
                if c.type == "use_as_clause":
                    names.append([self.t(self.fld(c, "path")), self.t(self.fld(c, "alias"))])
                else:
                    names.append([self.t(c), ""])
            self.facts.imports.append(ImportRef(module=base, names=names, line=line))
        elif arg.type == "use_as_clause":
            self.facts.imports.append(ImportRef(module=self.t(self.fld(arg, "path")), alias=self.t(self.fld(arg, "alias")), line=line))
        else:
            self.facts.imports.append(ImportRef(module=self.t(arg), line=line))

    def items(self, node, prefix: str, in_test_mod: bool) -> None:
        for ch in node.named_children:
            ty = ch.type
            if ty == "use_declaration":
                self.use_decl(ch)
            elif ty == "mod_item":
                name = self.t(self.fld(ch, "name"))
                body = self.fld(ch, "body")
                if body is None:
                    self.facts.imports.append(ImportRef(module=name, line=ch.start_point[0] + 1, kind="mod"))
                else:
                    _, attrs = self.leading(ch)
                    self.items(body, f"{prefix}{name}.", in_test_mod or any("cfg(test)" in a for a in attrs))
            elif ty == "function_item":
                self.func(ch, prefix, "")
            elif ty in ("struct_item", "enum_item", "trait_item", "union_item"):
                self.type_item(ch, prefix)
            elif ty == "impl_item":
                self.impl(ch, prefix)
            elif ty in ("const_item", "static_item"):
                name = self.t(self.fld(ch, "name"))
                self.add("constant", name, f"{prefix}{name}", ch, signature=" ".join(self.t(ch).split())[:120], exported=self.t(ch).startswith("pub"))

    def func(self, n, prefix: str, owner: str) -> None:
        name = self.t(self.fld(n, "name"))
        doc, attrs = self.leading(n)
        qual = f"{owner}.{name}" if owner else f"{prefix}{name}"
        tags, route = [], ""
        if any(re.search(r"#\[\s*(\w+::)*test\b", a) for a in attrs):
            tags.append("test"); self.facts.tests.append({"name": qual, "line": n.start_point[0] + 1}); self.facts.is_test = True
        for a in attrs:
            m = self.ROUTE_ATTR.search(a)
            if m:
                route = f"{m.group(1).upper()} {m.group(2)}"; tags.append("api")
                self.facts.apis.append(ApiRoute(m.group(1).upper(), m.group(2), qual, n.start_point[0] + 1, "actix/rocket"))
        if any(c.type == "function_modifiers" and "async" in self.t(c) for c in n.children):
            tags.append("async")
        self.add("method" if owner else "function", name, qual, n, owner, signature=self.signature(n), doc=doc,
                 calls=self.calls(self.fld(n, "body") or n), decorators=[a[:80] for a in attrs], tags=tags, route=route,
                 exported=self.t(n).startswith("pub"))

    def type_item(self, n, prefix: str) -> None:
        name = self.t(self.fld(n, "name"))
        kind = {"struct_item": "struct", "union_item": "struct", "enum_item": "enum", "trait_item": "trait"}[n.type]
        doc, attrs = self.leading(n)
        derives = set(re.findall(r"\w+", " ".join(a for a in attrs if "derive" in a)))
        tags, extra = [], {}
        if derives & self.MODEL_DERIVES:
            tags.append("model"); extra = {"framework": "diesel/sqlx/sea-orm", "fields": [self.t(f) for f in self.walk(n, {"field_identifier"})][:40]}
        bases = [strip_generics(self.t(x)) for x in n.children_by_field_name("bounds")] if kind == "trait" else []
        qual = f"{prefix}{name}"
        self.add(kind, name, qual, n, signature=self.signature(n), doc=doc, decorators=[a[:80] for a in attrs], tags=tags, extra=extra,
                 bases=bases, exported=self.t(n).startswith("pub"))
        if kind == "trait":
            body = self.fld(n, "body")
            for m in (body.named_children if body is not None else []):
                if m.type == "function_item":
                    self.func(m, prefix, qual)

    def impl(self, n, prefix: str) -> None:
        ty = strip_generics(self.t(self.fld(n, "type")))
        trait = strip_generics(self.t(self.fld(n, "trait"))) if self.fld(n, "trait") is not None else ""
        ty = re.sub(r"^&?\s*(mut\s+)?", "", ty).split("::")[-1]
        body = self.fld(n, "body")
        if trait:
            for s in self.facts.symbols:
                if s.name == ty and s.kind in ("struct", "enum") and trait not in s.bases:
                    s.bases.append(trait)
        for m in (body.named_children if body is not None else []):
            if m.type == "function_item":
                self.func(m, prefix, ty)

    def api_pass(self) -> None:
        for n in self.walk(self.root, {"call_expression"}):
            fn = self.fld(n, "function")
            if fn is None or fn.type != "field_expression" or self.t(self.fld(fn, "field")) != "route":
                continue
            args = self.fld(n, "arguments")
            if args is None or len(args.named_children) < 2 or args.named_children[0].type != "string_literal":
                continue
            path = self.string_value(args.named_children[0])
            inner = args.named_children[1]
            if not path.startswith("/") or inner.type != "call_expression":
                continue
            m = norm_callee(self.t(self.fld(inner, "function"))).split(".")[-1]
            iargs = self.fld(inner, "arguments")
            handler = self.t(iargs.named_children[0]).split("::")[-1] if iargs is not None and iargs.named_children else ""
            self.facts.apis.append(ApiRoute(HTTP_WORDS.get(m, "ANY"), path, handler, n.start_point[0] + 1, "axum"))


# ======================================================================================================
class PyTsVisitor(Visitor):
    """Error-tolerant Python extraction, used only when `ast` can't parse the file (syntax errors, Python 2, partial files)."""

    language = "python"
    call_types = ("call",)

    def run(self) -> None:
        self.block(self.root, "", "")
        for n in self.walk(self.root, {"import_statement", "import_from_statement"}):
            if n.type == "import_statement":
                for c in n.named_children:
                    nm = self.fld(c, "name") if c.type == "aliased_import" else c
                    self.facts.imports.append(ImportRef(module=self.t(nm), alias=self.t(self.fld(c, "alias")) if c.type == "aliased_import" else "", line=n.start_point[0] + 1))
            else:
                mod = self.fld(n, "module_name")
                text = self.t(mod)
                level = len(text) - len(text.lstrip("."))
                names = [[self.t(self.fld(c, "name")), self.t(self.fld(c, "alias"))] if c.type == "aliased_import" else [self.t(c), ""]
                         for c in n.children_by_field_name("name")]
                self.facts.imports.append(ImportRef(module=text.lstrip("."), level=level, names=names, line=n.start_point[0] + 1))

    def docstring(self, n) -> str:
        body = self.fld(n, "body")
        if body is not None and body.named_children and body.named_children[0].type == "expression_statement":
            s = body.named_children[0].named_children[0] if body.named_children[0].named_children else None
            if s is not None and s.type == "string":
                return " ".join(self.string_value(s).split())[:300]
        return ""

    def block(self, node, prefix: str, parent: str) -> None:
        for ch in node.named_children:
            d = ch
            decos: list[str] = []
            if ch.type == "decorated_definition":
                d = self.fld(ch, "definition")
                decos = [self.t(c) for c in ch.named_children if c.type == "decorator"]
            if d is None:
                continue
            if d.type == "function_definition":
                name = self.t(self.fld(d, "name"))
                self.add("method" if parent else "function", name, f"{prefix}{name}", ch, parent, signature=self.signature(d),
                         doc=self.docstring(d), calls=self.calls(self.fld(d, "body") or d), decorators=decos[:6], exported=not name.startswith("_"))
            elif d.type == "class_definition":
                name = self.t(self.fld(d, "name"))
                sc = self.fld(d, "superclasses")
                bases = [self.t(x) for x in (sc.named_children if sc is not None else [])]
                self.add("class", name, f"{prefix}{name}", ch, parent, signature=self.signature(d), doc=self.docstring(d), bases=bases,
                         decorators=decos[:6], exported=not name.startswith("_"))
                body = self.fld(d, "body")
                if body is not None:
                    self.block(body, f"{prefix}{name}.", f"{prefix}{name}")
            elif d.type in ("if_statement", "try_statement", "with_statement") and not parent:
                for sub in d.named_children:
                    if sub.type in ("block", "else_clause", "except_clause", "finally_clause"):
                        self.block(sub, prefix, parent)


VISITORS = {"python": PyTsVisitor, "javascript": JsVisitor, "typescript": TsVisitor, "tsx": TsVisitor, "java": JavaVisitor,
            "c": CVisitor, "cpp": CppVisitor, "go": GoVisitor, "rust": RustVisitor}
