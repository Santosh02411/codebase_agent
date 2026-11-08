"""Project-aware checks for JavaScript / TypeScript / JSX / TSX (on top of the syntax and pattern rules in treecheck.py):

  JS-IMPORT        a relative import ('./Hedaer') that does not resolve to a file; with a "did you mean" from the sibling files
  JS-PACKAGE       a package import that is not listed in package.json (typos like 'reactt'), when package.json exists and no node_modules is present
  JS-EXPORT        a named or default import that the target module does not export
  JS-UNDEFINED     an identifier (including a JSX component or a hook) that is used but never declared or imported, in a file that is an ES module
                   (module scope has no implicit globals). Browser and Node globals are known; unknown names in a near-miss of a declared name get high severity.

All of it is static: dynamic imports with computed paths, bundler aliases (`@/x`, `~/x`) and globals injected by <script> tags cannot be checked and are skipped."""
from __future__ import annotations
import difflib
import json
import re
import posixpath
from .pycheck import Finding
from .treecheck import JS_GLOBALS, _parse, _snippet, _IDENT

NODE_BUILTINS = set("assert async_hooks buffer child_process cluster console constants crypto dgram diagnostics_channel dns domain events fs http http2 https inspector module net os path perf_hooks process punycode querystring readline repl stream string_decoder sys timers tls trace_events tty url util v8 vm wasi worker_threads zlib".split())
RESOLVE_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json", ".css", ".scss", ".sass", ".less", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp3", ".mp4", ".woff", ".woff2", ".ttf", ".md", ".txt", ".html")
EXTRA_GLOBALS = set("""HTMLElement getComputedStyle matchMedia scrollTo scrollBy open close print focus blur stop postMessage addEventListener removeEventListener dispatchEvent requestIdleCallback cancelIdleCallback
innerWidth innerHeight outerWidth outerHeight scrollX scrollY pageXOffset pageYOffset devicePixelRatio name length closed event origin status opener onload onerror onresize onscroll
DOMParser XMLSerializer Notification Storage StorageEvent CSS Option Audio Image BroadcastChannel MessageChannel MessagePort ReadableStream WritableStream TransformStream CompressionStream
DecompressionStream TextEncoderStream TextDecoderStream WebAssembly Iterator AsyncIterator WeakRef FinalizationRegistry Temporal EventSource MediaRecorder MediaStream RTCPeerConnection Intl
define importScripts exports module require __webpack_require__ __dirname __filename global GLOBAL root jest describe it test expect beforeEach afterEach beforeAll afterAll vi cy Cypress
import meta ImportMeta process Buffer setImmediate clearImmediate reportError scheduler navigator speechSynthesis visualViewport customElements indexedDB caches clientInformation frameElement""".split())
GLOBAL_PATTERNS = re.compile(r"^(HTML|SVG|DOM|CSS|Web|Media|Audio|Intersection|Mutation|Resize|Pointer|Mouse|Keyboard|Touch|Focus|Wheel|Drag|Clipboard|Animation|Transition|Performance|Text|Range|Selection|Abort|Gamepad|Speech|Visual|Payment|Credential|Geolocation|Service|Shared|Subtle|Crypto|Idle|Rtc|RTC|XML|Navigation|Page|Progress|Promise|Storage|Cache|Stream|Readable|Writable|Compression|Declarative|Custom|Form|Input|Event|File|Blob|Header|Request|Response|URL|Worker|Window|Document|Element|Node|Attr|Comment|Shadow|Slot|Template|Tree|Xpath|XPath)[A-Za-z0-9]*$|^[A-Z][A-Za-z0-9]*(Event|Error|Observer|Element|Exception|Array|Reader|Writer|Request|Response|Handler|Callback|Listener|Context|Controller|Provider|Registry)$")
DECL_PARENTS = {"function_declaration", "generator_function_declaration", "class_declaration", "abstract_class_declaration", "formal_parameters", "required_parameter", "optional_parameter", "catch_clause", "import_specifier",
                "import_clause", "namespace_import", "named_imports", "labeled_statement", "rest_pattern", "array_pattern", "object_pattern", "shorthand_property_identifier_pattern", "enum_declaration", "interface_declaration",
                "type_alias_declaration", "type_parameter", "namespace_export", "break_statement", "continue_statement", "function_expression", "function", "generator_function", "class", "method_definition", "internal_module", "module",
                "pair_pattern", "object_assignment_pattern", "jsx_namespace_name", "export_specifier"}
FIELD_ONLY = {"member_expression": "object", "subscript_expression": "object", "variable_declarator": "value", "assignment_pattern": "right", "arrow_function": "body", "pair": "value", "for_in_statement": "right",
              "public_field_definition": "value", "field_definition": "value", "property_signature": "value", "jsx_attribute": "value"}


def _ext(rel: str) -> str:
    return posixpath.splitext(rel)[1].lower()


class JsProject:
    """What the project's other JS/TS files and package.json provide."""
    def __init__(self, texts: dict[str, str], all_paths: set[str]) -> None:
        self.texts, self.all_paths = texts, all_paths
        self.deps: set[str] | None = None
        raw = texts.get("package.json")
        if raw is None and "package.json" in all_paths:
            raw = None
        if raw:
            try:
                pj = json.loads(raw)
                self.deps = set()
                for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                    self.deps |= set((pj.get(k) or {}).keys())
                if pj.get("name"):
                    self.deps.add(pj["name"])
            except ValueError:
                self.deps = None
        self.has_node_modules = "node_modules/.present" in all_paths
        self.top_dirs = {p.split("/")[0] for p in all_paths if "/" in p}
        self._exports: dict[str, tuple[set[str], bool, bool] | None] = {}
        self.dir_index: dict[str, list[str]] = {}
        for p in all_paths:
            self.dir_index.setdefault(posixpath.dirname(p), []).append(p)

    def resolve(self, from_file: str, spec: str) -> str | None:
        base = posixpath.normpath(posixpath.join(posixpath.dirname(from_file), spec))
        if base.startswith(".."):
            return None
        cands = [base] + [base + e for e in RESOLVE_EXT] + [posixpath.join(base, "index" + e) for e in (".js", ".jsx", ".ts", ".tsx", ".mjs")]
        if _ext(base) in (".js", ".jsx", ".mjs", ".cjs"):                    # TypeScript projects import "./x.js" for x.ts
            stem = base.rsplit(".", 1)[0]
            cands += [stem + e for e in (".ts", ".tsx")]
        return next((c for c in cands if c in self.all_paths), None)

    def siblings(self, from_file: str, spec: str) -> list[str]:
        d = posixpath.normpath(posixpath.join(posixpath.dirname(from_file), posixpath.dirname(spec)))
        names = {posixpath.splitext(posixpath.basename(p))[0] for p in self.dir_index.get(d, [])}
        names |= {p.rsplit("/", 1)[-1] for p in self.dir_index.get(d, [])}
        return sorted(names)

    def exports(self, rel: str, lang: str):
        """(named exports, has default, open) for a module. `open` = CommonJS or `export *` (we cannot enumerate)."""
        if rel in self._exports:
            return self._exports[rel]
        text = self.texts.get(rel)
        res = None
        if text is not None and _ext(rel) in (".js", ".jsx", ".ts", ".tsx", ".mjs"):
            tree = _parse("tsx" if _ext(rel) == ".tsx" else "typescript" if _ext(rel) == ".ts" else "javascript", text.encode("utf-8", "replace"))
            if tree is not None:
                names: set[str] = set(); default = False; open_ = False
                src = text.encode("utf-8", "replace")
                for n in tree.root_node.children:
                    if n.type == "export_statement":
                        dec = n.child_by_field_name("declaration")
                        kinds = [c.type for c in n.children]
                        if "default" in kinds:
                            default = True
                        if dec is not None:
                            if dec.type in ("function_declaration", "class_declaration", "generator_function_declaration", "interface_declaration", "type_alias_declaration", "enum_declaration", "abstract_class_declaration"):
                                nm = dec.child_by_field_name("name")
                                if nm is not None:
                                    names.add(_snippet(src, nm, 100))
                            else:
                                for d in dec.children:
                                    if d.type == "variable_declarator":
                                        nm = d.child_by_field_name("name")
                                        if nm is not None:
                                            names.update(_IDENT.findall(_snippet(src, nm, 300)))
                        for c in n.children:
                            if c.type == "export_clause":
                                for sp in c.children:
                                    if sp.type == "export_specifier":
                                        nm = sp.child_by_field_name("alias") or sp.child_by_field_name("name")
                                        if nm is not None:
                                            t = _snippet(src, nm, 100)
                                            names.add(t)
                                            if t == "default":
                                                default = True
                            if c.type == "*" or (c.type == "namespace_export"):
                                open_ = True
                        if "*" in kinds:
                            open_ = True
                if re.search(r"\b(module\.exports|exports\.\w+)\s*=", text):
                    open_ = True
                res = (names, default, open_)
        self._exports[rel] = res
        return res


def _spec_nodes(tree_root, src: bytes):
    """Import-like statements: (kind, specifier text, node, import node) for `import`, `export ... from`, `require()` and dynamic `import()` with a literal."""
    out = []
    stack = [tree_root]
    while stack:
        n = stack.pop()
        t = n.type
        if t in ("import_statement", "export_statement"):
            s = n.child_by_field_name("source")
            if s is not None:
                out.append(("import" if t == "import_statement" else "reexport", _snippet(src, s, 300).strip("'\"`"), s, n))
        elif t == "call_expression":
            f = n.child_by_field_name("function")
            args = n.child_by_field_name("arguments")
            if f is not None and args is not None and args.named_child_count >= 1 and _snippet(src, f, 20) in ("require", "import"):
                a = args.named_children[0]
                if a.type == "string":
                    out.append(("require", _snippet(src, a, 300).strip("'\"`"), a, n))
        stack.extend(n.children)
    return out


def _import_names(imp_node, src: bytes):
    """(default name, [named imported names]) of an `import` statement."""
    default = None; named: list[tuple[str, object]] = []
    for c in imp_node.children:
        if c.type == "import_clause":
            for d in c.children:
                if d.type == "identifier":
                    default = (_snippet(src, d, 100), d)
                elif d.type == "named_imports":
                    for sp in d.children:
                        if sp.type == "import_specifier":
                            nm = sp.child_by_field_name("name")
                            if nm is not None:
                                named.append((_snippet(src, nm, 100), nm))
    return default, named


def _suggest(name: str, pool, n: int = 1):
    return difflib.get_close_matches(name, [p for p in pool if p and p != name], n=n, cutoff=0.7)


def project_checks(rel: str, lang: str, text: str, proj: JsProject) -> list[Finding]:
    src = text.encode("utf-8", "replace")
    tree = _parse(lang, src)
    if tree is None:
        return []
    out: list[Finding] = []
    root = tree.root_node
    is_module = any(c.type in ("import_statement", "export_statement") for c in root.children)
    for kind, spec, node, stmt in _spec_nodes(root, src):
        r, c = node.start_point
        if not spec:
            continue
        if spec.startswith("."):
            tgt = proj.resolve(rel, spec)
            if tgt is None:
                sug = _suggest(posixpath.basename(spec), proj.siblings(rel, spec))
                out.append(Finding("JS-IMPORT", "import-error", "high", f"Cannot resolve import `{spec}`: no such file or folder." + (f" Did you mean `{posixpath.join(posixpath.dirname(spec), sug[0])}`?" if sug else ""), r + 1, c, c + len(spec) + 2,
                                   fix="Fix the path or the file name (names are case-sensitive on most servers)."))
            elif kind == "import":
                ex = proj.exports(tgt, lang)
                if ex is not None:
                    names, has_default, open_ = ex
                    default, named = _import_names(stmt, src)
                    if default and not has_default and not open_:
                        d, dn = default
                        rr, cc = dn.start_point
                        out.append(Finding("JS-EXPORT", "import-error", "high", f"`{spec}` has no default export, but `{d}` is imported as the default.", rr + 1, cc, cc + len(d), fix="Use a named import `{ ... }`, or add `export default` to the module."))
                    for nm, n in named:
                        if nm not in names and not open_ and not (nm == "default" and has_default):
                            rr, cc = n.start_point
                            sug = _suggest(nm, names)
                            out.append(Finding("JS-EXPORT", "import-error", "high", f"`{spec}` does not export `{nm}`." + (f" Did you mean `{sug[0]}`?" if sug else ""), rr + 1, cc, cc + len(nm),
                                               fix=f"{posixpath.basename(tgt)} exports: {', '.join(sorted(names)[:10]) or '(nothing named)'}" + (" and a default." if has_default else ".")))
        elif proj.deps is not None and not proj.has_node_modules and not spec.startswith(("node:", "data:", "http", "virtual:", "~", "@/", "#", "/")):
            parts = spec.split("/")
            pkg = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
            if pkg in NODE_BUILTINS or pkg in proj.deps or pkg in proj.top_dirs or "." in pkg and pkg.endswith((".css", ".json")):
                continue
            sug = _suggest(pkg, proj.deps)
            out.append(Finding("JS-PACKAGE", "import-error", "high" if sug else "medium", f"Package `{pkg}` is imported but not listed in package.json." + (f" Did you mean `{sug[0]}`?" if sug else ""), r + 1, c, c + len(spec) + 2,
                               confidence="high" if sug else "medium", fix=f"`npm install {pkg}`, or correct the name." if not sug else f"Use `{sug[0]}`."))
    out += _undeclared(rel, lang, src, root, strict=is_module)
    return out


def _undeclared(rel: str, lang: str, src: bytes, root, strict: bool = True) -> list[Finding]:
    declared: set[str] = set()
    loads: list[tuple[object, str, bool]] = []
    def collect(n, parent=None, in_err=False):
        t = n.type
        if n.is_missing:
            return
        if t == "ERROR":
            in_err = True
        if t in ("variable_declarator",):
            nm = n.child_by_field_name("name")
            if nm is not None:
                declared.update(_IDENT.findall(_snippet(src, nm, 800)))
        if t in ("function_declaration", "class_declaration", "generator_function_declaration", "function_expression", "function", "class", "enum_declaration", "interface_declaration", "type_alias_declaration",
                 "abstract_class_declaration", "internal_module", "module", "method_definition"):
            nm = n.child_by_field_name("name")
            if nm is not None:
                declared.add(_snippet(src, nm, 100))
        if t in ("formal_parameters", "required_parameter", "optional_parameter", "catch_clause", "import_clause", "import_specifier", "namespace_import", "named_imports", "rest_pattern", "array_pattern", "object_pattern",
                 "type_parameters", "type_parameter", "assignment_pattern", "arrow_function", "for_in_statement", "for_statement", "using_declaration"):
            if t == "arrow_function":
                p = n.child_by_field_name("parameter") or n.child_by_field_name("parameters")
                if p is not None:
                    declared.update(_IDENT.findall(_snippet(src, p, 800)))
            elif t == "for_in_statement":
                l = n.child_by_field_name("left")
                if l is not None:
                    declared.update(_IDENT.findall(_snippet(src, l, 300)))
            elif t == "assignment_pattern":
                l = n.child_by_field_name("left")
                if l is not None:
                    declared.update(_IDENT.findall(_snippet(src, l, 300)))
            elif t != "for_statement":
                declared.update(_IDENT.findall(_snippet(src, n, 800 if t not in ("catch_clause",) else 120)))
        if t == "identifier" or t == "shorthand_property_identifier":
            if parent is not None and _is_load(n, parent, src):
                loads.append((n, _snippet(src, n, 100), in_err))
        for ch in n.children:
            collect(ch, n, in_err)
    collect(root)
    out: list[Finding] = []
    reported: set[str] = set()
    pool = declared | JS_GLOBALS | EXTRA_GLOBALS
    for n, name, in_err in loads:
        if name in pool or name in reported or GLOBAL_PATTERNS.match(name) or name in ("undefined", "arguments", "this", "super"):
            continue
        sug = difflib.get_close_matches(name, [p for p in declared if len(p) >= 3], n=1, cutoff=0.72)
        jsx = n.parent is not None and n.parent.type.startswith("jsx_") and name[:1].isupper()
        hook = name.startswith("use") and name[3:4].isupper()
        if (in_err or not strict) and not (sug or jsx or hook):          # unparsable code, or a plain <script> (globals come from elsewhere): only clear-cut cases
            continue
        reported.add(name)
        r, c = n.start_point
        why = " It is used as a component, so rendering it throws a ReferenceError." if jsx else " Did you forget to import it from `react`?" if hook else ""
        out.append(Finding("JS-UNDEFINED", "name-error", "high" if (sug or jsx or hook) else "medium", f"`{name}` is not defined in this file (not declared, not imported, not a known global)." + (f" Did you mean `{sug[0]}`?" if sug else "") + why,
                           r + 1, c, c + len(name), confidence="high" if (sug or jsx or hook) else "medium",
                           fix=f"Import or declare `{name}`" + (f", or use `{sug[0]}`." if sug else ". If it is a global added by a <script> tag, ignore this.")))
    return out


def _is_load(n, parent, src: bytes) -> bool:
    t = parent.type
    if t in DECL_PARENTS:
        return False
    if t in FIELD_ONLY:
        f = parent.child_by_field_name(FIELD_ONLY[t])
        return f is not None and f == n
    if t.startswith("jsx_"):
        if t in ("jsx_opening_element", "jsx_self_closing_element", "jsx_closing_element"):
            name = _snippet(src, n, 100)
            return name[:1].isupper()
        return True
    if t in ("type_annotation", "type_arguments", "generic_type", "predefined_type", "type_query", "nested_type_identifier", "type_assertion", "as_expression", "satisfies_expression", "implements_clause", "extends_type_clause"):
        return False
    return True
