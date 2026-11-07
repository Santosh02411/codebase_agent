"""Stack-trace understanding: pull (file, line, function) frames out of an error report and map them onto repository files,
so a bug report starts retrieval at the exact code that failed instead of guessing from words."""
from __future__ import annotations
import re
from dataclasses import dataclass

_PY = re.compile(r'File "([^"]+)", line (\d+)(?:, in (\S+))?')
_PYTEST = re.compile(r"^([\w./\\-]+\.py):(\d+):", re.M)
_JS = re.compile(r"at (?:(?:async )?([\w$.<>\[\] ]+?) \()?((?:[A-Za-z]:)?[^\s():]+\.[jt]sx?):(\d+):\d+\)?")
_JAVA = re.compile(r"at ([\w.$<>]+)\(([\w$]+\.(?:java|kt)):(\d+)\)")
_GO = re.compile(r"^\s+((?:/|[\w.-]+/)[\w./-]*\.go):(\d+)", re.M)
_RUST = re.compile(r"-->\s+([\w./-]+\.rs):(\d+)")
_ERR = re.compile(r"^\s*([A-Za-z_][\w.]*(?:Error|Exception|Warning|Failure)|panic|assert\w*)\b[:\s](.*)$", re.M)
_FOREIGN = ("site-packages", "dist-packages", "node_modules", "/usr/lib/", "<frozen", "<string>", "<stdin>", "/lib/python")


@dataclass
class Frame:
    file: str
    line: int
    func: str = ""


def parse_frames(text: str) -> list[Frame]:
    out: list[Frame] = []
    for m in _PY.finditer(text):
        out.append(Frame(m.group(1), int(m.group(2)), m.group(3) or ""))
    for m in _PYTEST.finditer(text):
        out.append(Frame(m.group(1), int(m.group(2))))
    for m in _JS.finditer(text):
        out.append(Frame(m.group(2), int(m.group(3)), (m.group(1) or "").strip()))
    for m in _JAVA.finditer(text):
        out.append(Frame(m.group(2), int(m.group(3)), m.group(1).split(".")[-1]))
    for m in _GO.finditer(text):
        out.append(Frame(m.group(1), int(m.group(2))))
    for m in _RUST.finditer(text):
        out.append(Frame(m.group(1), int(m.group(2))))
    return [f for f in out if not any(x in f.file.replace("\\", "/") for x in _FOREIGN)]


def resolve_frames(frames: list[Frame], tree: list[str]) -> list[Frame]:
    """Map frame paths (often absolute, from someone else's machine) to repository paths by longest matching suffix.
    Frames outside the repository are dropped. Result is innermost-last as in the trace, de-duplicated."""
    files = {f.replace("\\", "/"): f for f in tree}
    out, seen = [], set()
    for fr in frames:
        p = fr.file.replace("\\", "/").lstrip("./")
        best = ""
        for norm in files:
            if (p.endswith("/" + norm) or p == norm or norm.endswith("/" + p)) and len(norm) > len(best):
                best = norm
        if best and (best, fr.line) not in seen:
            seen.add((best, fr.line))
            out.append(Frame(files[best], fr.line, fr.func))
    return out


def error_signature(text: str) -> str:
    """The last 'SomethingError: message' line of a report: the best single search string for the failure."""
    hits = _ERR.findall(text or "")
    if not hits:
        return ""
    name, msg = hits[-1]
    return f"{name}: {msg.strip()}"[:200]
