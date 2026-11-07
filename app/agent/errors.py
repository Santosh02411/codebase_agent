"""Understanding an error report: exception type, message, file, line, function, the variable involved, the call stack.

Works on Python, JavaScript/TypeScript, Java/Kotlin, Go and Rust traces, on log excerpts that contain one (including `Caused by` /
`During handling of the above exception` chains), and degrades to a plain-description report. Everything here is deterministic: the
model gets these facts as a starting point instead of having to dig them out of pasted text (and may refine them)."""
from __future__ import annotations
import re
from dataclasses import asdict, dataclass, field
from typing import Callable

from .trace import Frame, parse_frames, resolve_frames

_PY_EXC = re.compile(r"^\s*([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning|Failure|Timeout)|AssertionError|KeyboardInterrupt|StopIteration)(?::[ \t]?(.*))?$")
_JS_EXC = re.compile(r"^\s*(?:Uncaught |Unhandled \w+ )?((?:[A-Z]\w*)?(?:Error|Exception)): (.*)$")
_JAVA_EXC = re.compile(r'^\s*(?:Exception in thread "[^"]+" )?([\w.$]+(?:Exception|Error|Throwable)): ?(.*)$')
_JAVA_CAUSE = re.compile(r"^\s*Caused by: ([\w.$]+(?:Exception|Error|Throwable)): ?(.*)$")
_GO_PANIC = re.compile(r"^\s*panic: (.*)$")
_RUST_PANIC = re.compile(r"thread '[^']*' panicked at (?:[^:]+:\d+:\d+:?)?\s*(.*)$")
_HTTP = re.compile(r"(?:\bstatus(?:[_ ]code)?[=:\" ]+|HTTP/\d(?:\.\d)?\"? |\b)([45]\d\d)\b(?= (?:Internal|Bad|Not|Unauthorized|Forbidden|Service|Method|Too|Gateway|Unprocessable)|[\"',}\s]|$)")
_LEVEL = re.compile(r"\b(CRITICAL|FATAL|ERROR|SEVERE)\b")

CATEGORIES = [
    (r"NoneType|undefined|null|NullPointer|nil pointer|Cannot read propert", "missing value (None / null / undefined)"),
    (r"KeyError|IndexError|out of range|OutOfBounds|KeyNotFound|undefined key", "missing key or index"),
    (r"ModuleNotFound|ImportError|cannot import|Cannot find module|ClassNotFound|NoClassDefFound|unresolved import", "import / dependency"),
    (r"NameError|UnboundLocal|ReferenceError|is not defined|cannot find symbol", "undefined name"),
    (r"AttributeError|has no attribute|is not a function|NoSuchMethod|no field", "wrong attribute / method"),
    (r"TypeError|unsupported operand|not callable|not iterable|not subscriptable|ClassCast|mismatched types", "type mismatch"),
    (r"ValueError|invalid literal|NumberFormat|ParseError|JSONDecode|SyntaxError|Unexpected token|IllegalArgument", "invalid value / parse"),
    (r"ZeroDivision|divide by zero|division by zero", "division by zero"),
    (r"FileNotFound|ENOENT|No such file|NoSuchFile", "missing file"),
    (r"Permission|EACCES|Forbidden|Unauthorized|PermissionDenied|AccessDenied|\b40[13]\b", "permission / authentication"),
    (r"Timeout|timed out|ETIMEDOUT", "timeout"),
    (r"Connection|ECONNREFUSED|OperationalError|DatabaseError|IntegrityError|SQL|socket|Network", "connection / database"),
    (r"AssertionError|assert|expected .* (?:to|but)|AssertionFailed", "failed assertion"),
    (r"RecursionError|StackOverflow|maximum call stack", "runaway recursion"),
    (r"MemoryError|OutOfMemory|heap", "out of memory"),
]


@dataclass
class ErrorReport:
    source: str = "description"           # user | test run | description
    language: str = ""
    exception_type: str = ""
    message: str = ""
    category: str = ""
    file: str = ""                        # innermost frame that is in the repository
    line: int = 0
    function: str = ""
    code_line: str = ""
    variables: list[dict] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)    # in-repo frames, outermost first
    external_frames: int = 0
    chained: list[str] = field(default_factory=list)
    http_status: int = 0
    related_functions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def found(self) -> bool:
        return bool(self.exception_type or self.frames)

    def headline(self) -> str:
        what = f"{self.exception_type}: {self.message}".strip(": ") if self.exception_type else "error (no exception type found)"
        where = f" at {self.file}:{self.line}" + (f" in {self.function}()" if self.function else "") if self.file else ""
        return what[:200] + where


def _language(text: str) -> str:
    if "Traceback (most recent call last)" in text or re.search(r'File "[^"]+", line \d+', text):
        return "python"
    if re.search(r"^\s+at [\w.$<>]+\([\w$]+\.(?:java|kt):\d+\)", text, re.M) or "Exception in thread" in text:
        return "java"
    if re.search(r"^\s+at .+\.[jt]sx?:\d+:\d+\)?\s*$", text, re.M):
        return "javascript"
    if "goroutine " in text or re.search(r"^\s+/?[\w./-]+\.go:\d+", text, re.M):
        return "go"
    if "panicked at" in text or re.search(r"-->\s+[\w./-]+\.rs:\d+", text):
        return "rust"
    return ""


def _exceptions(text: str, lang: str) -> list[tuple[str, str]]:
    """Every (type, message) in the text, in order of appearance."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        if lang == "java":
            m = _JAVA_CAUSE.match(line) or _JAVA_EXC.match(line)
        elif lang == "go":
            m = _GO_PANIC.match(line)
            if m:
                out.append(("panic", m.group(1).strip())); continue
        elif lang == "rust":
            m = _RUST_PANIC.search(line)
            if m:
                out.append(("panic", m.group(1).strip())); continue
        elif lang == "javascript":
            m = _JS_EXC.match(line)
        else:
            m = _PY_EXC.match(line) or _JS_EXC.match(line) or _JAVA_EXC.match(line)
        if m and not line.lstrip().startswith(("File ", "at ", "#")):
            out.append((m.group(1), (m.group(2) or "").strip()))
    return out


def _category(etype: str, message: str) -> str:
    blob = f"{etype} {message}"
    for pat, name in CATEGORIES:
        if re.search(pat, blob, re.I):
            return name
    return ""


def infer_variables(etype: str, message: str, code_line: str) -> list[dict]:
    """Names the failure is about. From the message when it names them, otherwise candidates from the failing line."""
    out: list[dict] = []

    def add(name: str, how: str) -> None:
        if name and not any(v["name"] == name for v in out) and re.match(r"^[\w.$\-\[\]']+$", name):
            out.append({"name": name, "evidence": how})

    m = message
    for pat, how in ((r"name '([\w.]+)' is not defined", "undefined name in the message"), (r"local variable '(\w+)' (?:referenced|where)", "unbound local in the message"),
                     (r"has no attribute '(\w+)'", "missing attribute in the message"), (r"cannot import name '(\w+)'", "import name in the message"),
                     (r"No module named '([\w.]+)'", "missing module in the message"), (r"Cannot find module '([^']+)'", "missing module in the message"),
                     (r"Cannot read propert(?:y|ies) of (?:undefined|null) \(reading '(\w+)'\)", "property read on undefined/null"),
                     (r"Cannot set propert(?:y|ies) of (?:undefined|null) \(setting '(\w+)'\)", "property set on undefined/null"),
                     (r"(\w+) is not defined", "undefined name in the message"), (r"(\w+) is not a function", "not callable in the message"),
                     (r"(\w+)\(\) (?:takes|missing|got)", "call with wrong arguments"), (r'because "([^"]+)" is null', "null reference in the message"),
                     (r"KeyError: ?'?([^'\n]+)'?", "missing key"), (r"^'?([^'\n]+)'?$", "")):
        mm = re.search(pat, m)
        if mm and how:
            add(mm.group(1).replace("<local", "local"), how)
    if etype == "KeyError" and message:
        add(message.strip("'\" "), "missing key")
    if "NoneType" in message or "null" in message.lower() or "undefined" in message.lower():
        idents = [i for i in re.findall(r"[A-Za-z_][\w.]*", code_line) if i not in ("if", "else", "return", "for", "in", "not", "and", "or", "is", "None", "True", "False", "self", "def", "const", "let", "var")]
        attr = re.search(r"'NoneType' object has no attribute '(\w+)'", message)
        if attr:                                           # `thing.attr` in the failing line: `thing` is the None one
            for i in idents:
                if i.endswith("." + attr.group(1)):
                    add(i.rsplit(".", 1)[0], "receiver of the failing attribute access (likely None)")
        elif "unsupported operand" in message or "NoneType" in message:
            called = set(re.findall(r"([A-Za-z_][\w.]*)\s*\(", code_line))
            op = re.search(r"for ([^\s:]+): '(\w+)' and '(\w+)'", message)
            if op:                                         # `a / b` with 'int' and 'NoneType': the right-hand operand is the None one
                sym, lt, rt = op.groups()
                pm = re.search(r"([\w.\]\[\"']+?)\s*" + re.escape(sym) + r"\s*([\w.\]\[\"']+)", code_line)
                if pm:
                    add(pm.group(2) if rt == "NoneType" else pm.group(1), f"{'right' if rt == 'NoneType' else 'left'} operand of `{sym}` is None")
            for i in idents:
                if i not in called and ("." not in i or i.startswith("self.")):
                    add(i, "name used in the failing expression (one of them is None)")
        elif "subscriptable" in message or "iterable" in message or "callable" in message:
            for i in idents[:3]:
                add(i, "name in the failing expression (likely None)")
    if etype == "ZeroDivisionError" or "division by zero" in message:
        for mm in re.finditer(r"[/%]\s*([A-Za-z_][\w.]*)", code_line):
            add(mm.group(1), "divisor in the failing line")
    return out[:6]


def parse_error(text: str, tree: list[str], read_line: Callable[[str, int], str] | None = None, source: str = "user") -> ErrorReport:
    """Build an ErrorReport from pasted text. `tree` = repository files (to keep only in-repo frames), `read_line(file, n)` = source text of a line."""
    text = text or ""
    lang = _language(text)
    rep = ErrorReport(source=source, language=lang)
    excs = _exceptions(text, lang)
    if excs:
        # Python / JS print the final (most relevant) exception last; Java prints the wrapper first and the root cause in `Caused by`
        t, m = excs[-1] if lang in ("python", "") else excs[0]
        rep.exception_type, rep.message = t, m
        rep.chained = [f"{a}: {b}".strip(": ")[:160] for a, b in excs if (a, b) != (t, m)][:4]
        if lang == "java" and len(excs) > 1:
            rep.chained, (rep.exception_type, rep.message) = [f"{excs[0][0]}: {excs[0][1]}"[:160]], excs[-1]
    rep.category = _category(rep.exception_type, rep.message)
    h = _HTTP.search(text)
    rep.http_status = int(h.group(1)) if h else 0
    frame_text = text
    if lang == "java" and "Caused by:" in text:      # the innermost frame belongs to the root cause, whose trace is the last block
        frame_text = text[text.rindex("Caused by:"):]
    raw = parse_frames(frame_text)
    resolved = resolve_frames(raw, tree)
    rep.external_frames = max(0, len(raw) - len(resolved))
    if lang in ("javascript", "java", "go"):      # these print the innermost frame first
        resolved = list(reversed(resolved))
    rep.frames = [{"file": f.file, "line": f.line, "func": f.func} for f in resolved]
    if resolved:
        origin = resolved[-1]
        rep.file, rep.line, rep.function = origin.file, origin.line, origin.func if origin.func != "<module>" else ""
        if read_line:
            try:
                rep.code_line = read_line(origin.file, origin.line).strip()[:200]
            except (OSError, ValueError, IndexError):
                pass
    rep.variables = infer_variables(rep.exception_type, rep.message, rep.code_line)
    if not rep.exception_type and not rep.frames and not rep.http_status and _LEVEL.search(text):
        m2 = re.search(r"\b(?:CRITICAL|FATAL|ERROR|SEVERE)\b[^\n]*?[:\-\]]\s*(.{10,200})", text)
        rep.message = (m2.group(1) if m2 else "").strip()
        rep.category = _category("", rep.message)
    return rep


def from_test_output(output: str, tree: list[str], read_line=None) -> ErrorReport:
    """The report for a failing test run: pytest prints `E   Error: message` lines and `path:line: in func` frames."""
    lines = output.splitlines()
    e_lines = [l[1:].strip() for l in lines if l.startswith("E  ")]
    synthetic = output
    if e_lines:
        synthetic += "\n" + next((l for l in reversed(e_lines) if _PY_EXC.match(l)), e_lines[-1])
    rep = parse_error(synthetic, tree, read_line, source="test run")
    if not rep.exception_type:
        m = re.search(r"^E\s+(assert .*|AssertionError.*)$", output, re.M)
        if m:
            rep.exception_type, rep.message, rep.category = "AssertionError", m.group(1)[:200], "failed assertion"
    return rep
