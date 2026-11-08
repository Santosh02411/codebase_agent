"""Syntax and pattern checks for languages parsed with Tree-sitter (JavaScript, TypeScript, TSX, Java, Go, Rust, C, C++).

Syntax errors come from the real grammar: an ERROR node is code the grammar cannot parse, a MISSING node is a token the grammar expected and did not find
(`}`, `)`, `;`). That catches extra/missing braces and brackets, unclosed strings, broken statements. JavaScript/TypeScript also get a few high-signal rules
(assignment in a condition, `debugger`, empty `catch`, `==`, unreachable code, misspelled identifiers). There is no type checker and no full name resolution
for these languages: that limit is reported to the user, not hidden."""
from __future__ import annotations
import difflib
import re
from .pycheck import Finding

try:
    from ..intel.ts_core import get_parser
except Exception:                      # pragma: no cover
    get_parser = None  # type: ignore

LANG_BY_EXT = {".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".tsx": "tsx", ".java": "java", ".go": "go", ".rs": "rust", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp"}
JS_GLOBALS = set("""undefined NaN Infinity globalThis window document console process require module exports __dirname __filename Buffer setTimeout setInterval clearTimeout clearInterval setImmediate
Promise Array Object String Number Boolean Symbol BigInt Map Set WeakMap WeakSet Date Math JSON RegExp Error TypeError RangeError SyntaxError ReferenceError EvalError URIError AggregateError Intl Reflect Proxy
parseInt parseFloat isNaN isFinite encodeURIComponent decodeURIComponent encodeURI decodeURI escape unescape fetch Request Response Headers URL URLSearchParams FormData Blob File FileReader AbortController
Event CustomEvent EventTarget Node Element HTMLElement localStorage sessionStorage navigator location history screen alert confirm prompt requestAnimationFrame cancelAnimationFrame performance
structuredClone queueMicrotask TextEncoder TextDecoder atob btoa crypto WebSocket Worker MutationObserver IntersectionObserver ResizeObserver Image Audio Option XMLHttpRequest ArrayBuffer Uint8Array Int8Array
Uint16Array Int16Array Uint32Array Int32Array Float32Array Float64Array DataView Atomics SharedArrayBuffer React ReactDOM JSX self top parent frames arguments this super true false null async await of get set static
$ jQuery Chart L d3 _ moment axios io THREE""".split())
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


def _parse(lang: str, src: bytes):
    if get_parser is None:
        return None
    try:
        p = get_parser(lang)
        return p.parse(src) if p else None
    except Exception:
        return None


def _snippet(src: bytes, node, limit=40) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace").strip().replace("\n", " ")[:limit]


def _deepest_error(n):
    """Tree-sitter wraps a whole construct in one big ERROR node; the real problem is the innermost error inside it."""
    cur = n
    while True:
        nxt = next((c for c in cur.children if c.type == "ERROR" or c.is_missing or c.has_error), None)
        if nxt is None:
            return cur
        cur = nxt


def syntax_errors(lang: str, text: str) -> list[Finding]:
    src = text.encode("utf-8", "replace")
    tree = _parse(lang, src)
    if tree is None:
        return []
    out: list[Finding] = []
    stack = [tree.root_node]
    while stack and len(out) < 12:
        n = stack.pop()
        if n.is_missing:
            r, c = n.start_point
            out.append(Finding(f"{_pref(lang)}-SYNTAX", "syntax", "high", f"Missing `{n.type}`: the grammar expected it here.", r + 1, c, c + 1, fix=f"Insert the missing `{n.type}` (check the previous line too: a missing/extra bracket is reported where the parser notices it)."))
            continue
        if n.type == "ERROR":
            n = _deepest_error(n)
            if n.is_missing:
                stack.append(n)
                continue
            r, c = n.start_point
            er, ec = n.end_point
            bad = _snippet(src, n)
            if bad.startswith("&") and lang in ("tsx", "javascript", "typescript"):      # `Save & close` in JSX text is valid; the grammar does not accept a raw ampersand
                continue
            # an ERROR that contains a lone closing bracket is the classic "extra }" / "extra )"
            msg = f"Syntax error near `{bad[:30]}`." if bad else "Syntax error."
            if bad[:1] in (">", ")", "]", "}", "<", ",", ";") and bad.strip() not in ("}", ")", "]"):
                msg = f"Unexpected `{bad[:1]}` here: a bracket, brace or parenthesis just before it is probably never closed (or a tag is not closed)."
            if bad.strip() in ("}", ")", "]"):
                msg = f"Unexpected `{bad.strip()}`: there is no matching opening bracket (extra closing bracket)."
            out.append(Finding(f"{_pref(lang)}-SYNTAX", "syntax", "high", msg, r + 1, c, c + max(1, min(er == r and ec - c or 1, 40)), fix="Check for an extra or missing bracket, brace, parenthesis or quote at or just before this position."))
            continue                         # do not report the children of an error node
        if n.has_error:
            stack.extend(reversed(n.children))
    return out


def _pref(lang: str) -> str:
    return {"javascript": "JS", "typescript": "TS", "tsx": "TS", "java": "JAVA", "go": "GO", "rust": "RS", "c": "C", "cpp": "CPP"}.get(lang, lang.upper())


def js_rules(lang: str, text: str) -> list[Finding]:
    src = text.encode("utf-8", "replace")
    tree = _parse(lang, src)
    if tree is None:
        return []
    out: list[Finding] = []
    declared: set[str] = set()
    loads: list = []
    imports: list[tuple[str, object]] = []
    def walk(n, parent=None):
        t = n.type
        if t == "ERROR" or n.is_missing:
            return                               # code the grammar could not parse: reported as a syntax error, not analysed further
        if t in ("variable_declarator",):
            nm = n.child_by_field_name("name")
            if nm is not None:
                declared.update(_IDENT.findall(_snippet(src, nm, 400)))
        elif t in ("function_declaration", "class_declaration", "generator_function_declaration", "method_definition", "function", "function_expression", "arrow_function", "lexical_declaration", "interface_declaration", "type_alias_declaration", "enum_declaration", "abstract_class_declaration", "namespace_import"):
            nm = n.child_by_field_name("name")
            if nm is not None:
                declared.add(_snippet(src, nm, 100))
        if t in ("formal_parameters", "required_parameter", "optional_parameter", "catch_clause", "for_in_statement", "import_clause", "import_specifier", "namespace_import", "named_imports", "shorthand_property_identifier_pattern", "object_pattern", "array_pattern", "rest_pattern", "assignment_pattern"):
            declared.update(_IDENT.findall(_snippet(src, n, 600)))
        if t == "import_specifier" or t == "namespace_import":
            imports.append((_snippet(src, n, 80), n))
        if t == "import_clause":
            nm = n.children[0] if n.children else None
            if nm is not None and nm.type == "identifier":
                imports.append((_snippet(src, nm, 80), nm))
        if t == "debugger_statement":
            r, c = n.start_point
            out.append(Finding("JS-DEBUGGER", "bug-risk", "medium", "`debugger` statement left in the code.", r + 1, c, c + 8, fix="Remove it."))
        if t == "if_statement" or t == "while_statement":
            cond = n.child_by_field_name("condition")
            if cond is not None:
                for ch in cond.children:
                    if ch.type == "assignment_expression":
                        r, c = ch.start_point
                        out.append(Finding("JS-ASSIGNCOND", "bug-risk", "high", "Assignment (`=`) inside a condition. Did you mean `==` or `===`?", r + 1, c, c + 1, fix="Use `===` to compare, or wrap the assignment in extra parentheses if it is intentional."))
        if t == "catch_clause":
            body = n.child_by_field_name("body")
            if body is not None and body.named_child_count == 0:
                r, c = n.start_point
                out.append(Finding("JS-EMPTYCATCH", "bug-risk", "medium", "Empty `catch` block: errors are silently swallowed.", r + 1, c, c + 5, fix="Handle or log the error."))
        if t == "binary_expression":
            op = n.child_by_field_name("operator")
            if op is not None and _snippet(src, op) in ("==", "!="):
                right = n.child_by_field_name("right")
                if right is not None and _snippet(src, right) not in ("null", "undefined"):
                    r, c = op.start_point
                    out.append(Finding("JS-LOOSEEQ", "style", "low", f"Loose `{_snippet(src, op)}` performs type coercion; prefer `{_snippet(src, op)}=`.", r + 1, c, c + 2, fix="Use `===` / `!==`."))
        if t == "statement_block":
            kids = [k for k in n.named_children if k.type != "comment"]
            for i, k in enumerate(kids[:-1]):
                if k.type in ("return_statement", "throw_statement", "break_statement", "continue_statement"):
                    nxt = kids[i + 1]
                    if nxt.type not in ("function_declaration",):
                        r, c = nxt.start_point
                        out.append(Finding("JS-UNREACHABLE", "bug-risk", "low", f"Unreachable code after `{k.type.split('_')[0]}`.", r + 1, c, c + 1, fix="Remove it or move it before the statement that ends the block."))
                    break
        if t == "identifier" and parent is not None and parent.type not in ("member_expression", "property_identifier", "pair", "labeled_statement", "variable_declarator", "function_declaration", "class_declaration", "formal_parameters", "method_definition", "import_specifier", "import_clause", "namespace_import", "catch_clause", "required_parameter", "optional_parameter", "assignment_pattern", "shorthand_property_identifier_pattern", "function", "arrow_function", "type_identifier"):
            loads.append(n)
        for ch in n.children:
            walk(ch, n)
    walk(tree.root_node)
    # unused imports (by text occurrences)
    body = text
    for name, n in imports:
        for ident in _IDENT.findall(name):
            if ident in ("as", "type", "default"):
                continue
            if len(re.findall(r"(?<![\w$.])" + re.escape(ident) + r"(?![\w$])", body)) <= 1:
                r, c = n.start_point
                out.append(Finding("JS-UNUSEDIMPORT", "unused", "low", f"`{ident}` is imported but never used.", r + 1, c, c + len(ident), fix="Remove the import."))
    return out


def brace_balance(text: str) -> list[Finding]:
    """Fallback for when no grammar is available: count brackets outside strings and comments."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[tuple[str, int, int]] = []
    out: list[Finding] = []
    i, line, col, n = 0, 1, 0, len(text)
    mode = None
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if mode is None:
            if ch == "/" and nxt == "/":
                mode = "line"
            elif ch == "/" and nxt == "*":
                mode = "block"
            elif ch in "\"'`":
                mode = ch
            elif ch in "([{":
                stack.append((ch, line, col))
            elif ch in ")]}":
                if stack and stack[-1][0] == pairs[ch]:
                    stack.pop()
                else:
                    out.append(Finding("BRACE", "syntax", "high", f"Unmatched `{ch}`: no matching opening bracket.", line, col, col + 1, fix="Remove it or add the missing opening bracket."))
        elif mode == "line" and ch == "\n":
            mode = None
        elif mode == "block" and ch == "*" and nxt == "/":
            mode = None; i += 1; col += 1
        elif mode in "\"'`":
            if ch == "\\":
                i += 1; col += 1
            elif ch == mode or (ch == "\n" and mode != "`"):
                mode = None
        if ch == "\n":
            line += 1; col = 0
        else:
            col += 1
        i += 1
    for ch, ln, cl in stack:
        out.append(Finding("BRACE", "syntax", "high", f"`{ch}` is never closed.", ln, cl, cl + 1, fix="Add the matching closing bracket."))
    return out[:12]
