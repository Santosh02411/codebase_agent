"""Strict validation of data and markup files: JSON, YAML, TOML, HTML, CSS."""
from __future__ import annotations
import json
import re
from html.parser import HTMLParser
from .pycheck import Finding
from .treecheck import brace_balance

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr", "command", "keygen", "menuitem"}
OPTIONAL_CLOSE = {"p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot", "option", "optgroup", "colgroup", "caption", "rt", "rp"}


def check_json(text: str) -> list[Finding]:
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        return [Finding("JSON-SYNTAX", "syntax", "high", f"Invalid JSON: {e.msg}", e.lineno, max(0, e.colno - 1), fix="Check for trailing commas, missing quotes/commas, single quotes (JSON needs double quotes) and unclosed braces.")]
    except ValueError as e:
        return [Finding("JSON-SYNTAX", "syntax", "high", f"Invalid JSON: {e}", 1)]
    return []


def check_yaml(text: str) -> list[Finding]:
    try:
        import yaml
    except ImportError:
        return []
    try:
        list(yaml.safe_load_all(text))
    except yaml.YAMLError as e:
        m = getattr(e, "problem_mark", None)
        return [Finding("YAML-SYNTAX", "syntax", "high", f"Invalid YAML: {getattr(e, 'problem', None) or e}", (m.line + 1) if m else 1, m.column if m else 0, fix="Check indentation (spaces only), colons after keys and quoting.")]
    except Exception:
        return []
    return []


def check_toml(text: str) -> list[Finding]:
    try:
        import tomllib
    except ImportError:
        return []
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        m = re.search(r"line (\d+), column (\d+)", str(e))
        return [Finding("TOML-SYNTAX", "syntax", "high", f"Invalid TOML: {e}", int(m.group(1)) if m else 1, int(m.group(2)) - 1 if m else 0)]
    return []


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int, int]] = []
        self.out: list[Finding] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append((tag, *self.getpos()))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for t, ln, cl in self.stack[i + 1:]:
                    if t not in OPTIONAL_CLOSE:
                        self.out.append(Finding("HTML-UNCLOSED", "syntax", "high", f"`<{t}>` is never closed before `</{tag}>`.", ln, cl, fix=f"Add `</{t}>`."))
                del self.stack[i:]
                return
        ln, cl = self.getpos()
        self.out.append(Finding("HTML-STRAYCLOSE", "syntax", "high", f"`</{tag}>` has no matching opening tag.", ln, cl, fix="Remove it or add the opening tag."))


def check_html(text: str) -> list[Finding]:
    p = _Tags()
    try:
        p.feed(text); p.close()
    except Exception:
        return []
    out = p.out
    for t, ln, cl in p.stack:
        if t not in OPTIONAL_CLOSE and t not in ("html", "body", "head"):
            out.append(Finding("HTML-UNCLOSED", "syntax", "high", f"`<{t}>` is never closed.", ln, cl, fix=f"Add `</{t}>`."))
    # embedded <script> / <style> blocks are checked for balanced brackets
    for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", text, re.S | re.I):
        start = text.count("\n", 0, m.start(1))
        for f in brace_balance(m.group(1)):
            f.line += start; out.append(f)
    return out[:20]


def check_css(text: str) -> list[Finding]:
    stripped = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return brace_balance(stripped)
