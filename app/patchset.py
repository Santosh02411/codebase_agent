"""Multi-file patch engine.

A patch is described by a `PatchSpec` (any mix of the four forms below) and turned into a `PatchSet`: the exact before/after text of
every file it touches plus the unified diff. Nothing is written until `apply_patchset`, and that writes atomically with an undo record.

  edits         [{file, search, replace}]   targeted replacement; `search` must be unique. Falls back to a whitespace-tolerant
                                            line match (re-indenting the replacement) when the exact text is not found
  unified_diff  "--- a/x\n+++ b/x\n@@ ..."  a real unified diff; hunks are located by their CONTEXT, not by (usually wrong) line numbers
  rewrites      [{path, content}]           whole-file replacement of an existing file
  new_files     [{path, content}]           create files that do not exist
  delete_files  [path]                      remove files (explicit, counted, shown in the diff)

Existing code is preserved: line endings (CRLF/LF) and a BOM are kept, trailing-newline state is kept, file mode is kept, and a change
that would leave a previously valid .py/.json/.toml file unparseable is rejected before it can be applied.
Errors are written for the model: they say what failed and show the nearest real text so the next attempt can be right."""
from __future__ import annotations
import ast
import base64
import difflib
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .utils import safe_path

MAX_FILES = 25
MAX_DELETES = 5
MAX_FILE_BYTES = 1_000_000
BOM = "\ufeff"


class PatchError(ValueError):
    """The patch cannot be built or applied. The message is meant to be fed back to the model."""


class StaleError(PatchError):
    """A file changed on disk after the patch was proposed."""


@dataclass
class PatchSpec:
    edits: list[dict] = field(default_factory=list)
    new_files: list[dict] = field(default_factory=list)
    delete_files: list[str] = field(default_factory=list)
    rewrites: list[dict] = field(default_factory=list)
    unified_diff: str = ""

    @classmethod
    def from_dict(cls, d: dict | None) -> "PatchSpec":
        d = d or {}
        return cls(edits=[e for e in d.get("edits") or [] if isinstance(e, dict)], new_files=[e for e in d.get("new_files") or [] if isinstance(e, dict)],
                   delete_files=[str(x) for x in d.get("delete_files") or [] if x], rewrites=[e for e in d.get("rewrites") or [] if isinstance(e, dict)],
                   unified_diff=str(d.get("unified_diff") or ""))

    def empty(self) -> bool:
        return not (self.edits or self.new_files or self.delete_files or self.rewrites or self.unified_diff.strip())

    def to_dict(self) -> dict:
        return {"edits": self.edits, "new_files": self.new_files, "delete_files": self.delete_files, "rewrites": self.rewrites, "unified_diff": self.unified_diff}


@dataclass
class FileChange:
    path: str
    op: str                       # modify | create | delete
    old: str | None               # text before (normalised to \n), None for create
    new: str | None               # text after, None for delete
    base_hash: str | None         # sha256 of the file bytes the patch was built against (None: file did not exist)
    eol: str = "\n"
    bom: bool = False
    fuzzy: bool = False
    notes: list[str] = field(default_factory=list)
    diff: str = ""
    additions: int = 0
    deletions: int = 0

    def summary(self) -> dict:
        return {"path": self.path, "op": self.op, "additions": self.additions, "deletions": self.deletions, "fuzzy": self.fuzzy, "notes": self.notes}


@dataclass
class PatchSet:
    changes: list[FileChange]

    @property
    def diff(self) -> str:
        return "".join(c.diff for c in self.changes)

    @property
    def paths(self) -> list[str]:
        return [c.path for c in self.changes]

    def get(self, path: str) -> FileChange | None:
        return next((c for c in self.changes if c.path == path), None)

    def stats(self) -> dict:
        return {"files": len(self.changes), "additions": sum(c.additions for c in self.changes), "deletions": sum(c.deletions for c in self.changes),
                "created": sum(c.op == "create" for c in self.changes), "deleted": sum(c.op == "delete" for c in self.changes),
                "modified": sum(c.op == "modify" for c in self.changes)}


# ---- reading / writing files faithfully -------------------------------------------------------------------
def check_path(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel.strip() or rel.endswith("/"):
        raise PatchError("a file path is required")
    parts = Path(rel.replace("\\", "/")).parts
    if ".git" in parts:
        raise PatchError(f"{rel}: the .git directory cannot be changed")
    try:
        p = safe_path(root, rel)
    except ValueError as e:
        raise PatchError(str(e))
    if (root / rel).is_symlink():
        raise PatchError(f"{rel} is a symbolic link; refusing to replace it")
    return p


def _hash(raw: bytes | None) -> str | None:
    return None if raw is None else hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes, rel: str) -> tuple[str, str, bool]:
    if len(raw) > MAX_FILE_BYTES:
        raise PatchError(f"{rel} is larger than {MAX_FILE_BYTES // 1000} KB; not editable by a patch")
    if b"\x00" in raw:
        raise PatchError(f"{rel} looks binary; not editable by a patch")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PatchError(f"{rel} is not valid UTF-8; not editable by a patch")
    bom = text.startswith(BOM)
    if bom:
        text = text[1:]
    crlf, lf = text.count("\r\n"), text.count("\n")
    eol = "\r\n" if crlf and crlf * 2 > lf else "\n"
    return text.replace("\r\n", "\n"), eol, bom


def _encode(text: str, eol: str, bom: bool) -> bytes:
    return ((BOM if bom else "") + (text.replace("\n", eol) if eol != "\n" else text)).encode("utf-8")


@dataclass
class _Entry:
    exists: bool
    raw_hash: str | None = None
    old: str | None = None
    text: str | None = None
    eol: str = "\n"
    bom: bool = False
    fuzzy: bool = False
    deleted: bool = False
    created: bool = False
    touched: bool = False
    notes: list[str] = field(default_factory=list)


# ---- syntax validation -------------------------------------------------------------------------------------
def syntax_error(path: str, text: str) -> str | None:
    try:
        if path.endswith(".py"):
            ast.parse(text)
        elif path.endswith(".json"):
            json.loads(text)
        elif path.endswith(".toml"):
            import tomllib
            tomllib.loads(text)
        elif path.endswith((".yml", ".yaml")):
            import yaml
            list(yaml.safe_load_all(text))
    except SyntaxError as e:
        return f"line {e.lineno}: {e.msg}"
    except (ValueError, ImportError) as e:   # JSONDecodeError / TOMLDecodeError are ValueErrors
        return str(e).splitlines()[0][:200] if not isinstance(e, ImportError) else None
    except Exception as e:  # noqa: BLE001 - yaml.YAMLError
        return str(e).splitlines()[0][:200]
    return None


# ---- locating text -----------------------------------------------------------------------------------------
def _closest(text: str, search: str, ctx: int = 3) -> str:
    """The nearest real text to a `search` that did not match, so the next attempt can copy it."""
    first = next((l.strip() for l in search.splitlines() if l.strip()), "")
    if not first:
        return ""
    lines = text.split("\n")
    stripped = [l.strip() for l in lines]
    match = difflib.get_close_matches(first, stripped, n=1, cutoff=0.6)
    if not match:
        return " No similar line exists in the file; re-read it before editing."
    i = stripped.index(match[0])
    lo, hi = max(0, i - ctx), min(len(lines), i + len(search.splitlines()) + ctx)
    excerpt = "\n".join(f"{n + 1:>5}| {lines[n]}" for n in range(lo, hi))
    return f" Closest existing text (lines {lo + 1}-{hi}):\n{excerpt}"


def _line_numbers(text: str, search: str) -> list[int]:
    out, start = [], 0
    while (i := text.find(search, start)) != -1:
        out.append(text.count("\n", 0, i) + 1)
        start = i + 1
    return out


def _windows(lines: list[str], block: list[str], norm) -> list[int]:
    n = len(block)
    if n == 0 or n > len(lines):
        return []
    nb = [norm(x) for x in block]
    return [i for i in range(len(lines) - n + 1) if all(norm(lines[i + k]) == nb[k] for k in range(n))]


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _indent_fn(pairs: list[tuple[str, str]]):
    """Learn how the model's indentation maps onto the file's from matched line pairs: a constant shift (2 -> 4 spaces everywhere
    +2) or a constant ratio (2-space style written for a 4-space file)."""
    if not pairs:
        return lambda ind: ind
    spaces = all(set(s + a) <= {" "} for s, a in pairs)
    if spaces:
        offs = {len(a) - len(s) for s, a in pairs}
        if len(offs) == 1:
            off = next(iter(offs))
            return lambda ind: " " * max(0, len(ind) + off) if set(ind) <= {" "} else ind
        ks = {round(len(a) / len(s), 3) for s, a in pairs if s}
        if len(ks) == 1 and all(s or not a for s, a in pairs):
            k = next(iter(ks))
            return lambda ind: " " * round(len(ind) * k) if set(ind) <= {" "} else ind
    s0, a0 = pairs[0]
    return lambda ind: a0 + ind[len(s0):] if ind.startswith(s0) else ind


def _reindent(new_lines: list[str], from_indent: str, to_indent: str) -> list[str]:
    if from_indent == to_indent:
        return new_lines
    out = []
    for l in new_lines:
        out.append(to_indent + l[len(from_indent):] if l.strip() and l.startswith(from_indent) else l)
    return out


def apply_edit(text: str, search: str, replace: str, path: str, fuzzy: bool = True) -> tuple[str, bool, str]:
    """-> (new_text, used_fuzzy, note). Exact unique match first; whitespace-tolerant unique line match as a fallback."""
    if not search:
        raise PatchError(f"edit in {path} has an empty `search`; use new_files to create a file or rewrites to replace one")
    n = text.count(search)
    if n == 1:
        i = text.index(search)
        return text[:i] + replace + text[i + len(search):], False, ""
    if n > 1:
        raise PatchError(f"`search` text in {path} must match exactly once (found {n}, at lines {_line_numbers(text, search)[:6]}). "
                         "Include more surrounding lines so it is unique.")
    if fuzzy:
        s_lines = search.strip("\n").split("\n")
        t_lines = text.split("\n")
        hits = _windows(t_lines, s_lines, lambda s: s.strip()) or _windows(t_lines, s_lines, lambda s: re.sub(r"\s+", " ", s.strip()))
        if len(hits) == 1:
            i = hits[0]
            fn = _indent_fn([(_indent_of(sl), _indent_of(t_lines[i + k])) for k, sl in enumerate(s_lines) if sl.strip()])
            r_lines = [fn(_indent_of(l)) + l.lstrip() if l.strip() else l for l in replace.strip("\n").split("\n")]
            out = t_lines[:i] + r_lines + t_lines[i + len(s_lines):]
            return "\n".join(out), True, f"matched ignoring whitespace differences at line {i + 1}"
        if len(hits) > 1:
            raise PatchError(f"`search` text in {path} must match exactly once (found {len(hits)} whitespace-insensitive matches, "
                             f"at lines {[h + 1 for h in hits[:6]]}). Include more surrounding lines.")
    raise PatchError(f"`search` text in {path} must match exactly once (found 0)." + _closest(text, search))


# ---- unified diff ------------------------------------------------------------------------------------------
@dataclass
class _Hunk:
    start: int
    old: list[str]
    new: list[str]
    ops: list[tuple[str, str]] = field(default_factory=list)   # (' ' | '-' | '+', text) in diff order


@dataclass
class _FilePatch:
    old_path: str
    new_path: str
    hunks: list[_Hunk]

    @property
    def is_create(self) -> bool:
        return self.old_path == "/dev/null"

    @property
    def is_delete(self) -> bool:
        return self.new_path == "/dev/null"


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _clean_path(p: str) -> str:
    p = p.split("\t")[0].strip().strip('"')
    if p == "/dev/null":
        return p
    return p[2:] if p.startswith(("a/", "b/")) else p


def parse_unified(diff: str) -> list[_FilePatch]:
    lines = diff.replace("\r\n", "\n").split("\n")
    out: list[_FilePatch] = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith(("rename from", "rename to", "copy from", "copy to", "GIT binary patch", "Binary files")):
            raise PatchError("renames, copies and binary diffs are not supported; use delete_files + new_files")
        if l.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            fp = _FilePatch(_clean_path(l[4:]), _clean_path(lines[i + 1][4:]), [])
            i += 2
            while i < len(lines) and not (lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")) \
                    and not lines[i].startswith("diff --git"):
                m = _HUNK.match(lines[i])
                if not m:
                    i += 1
                    continue
                h = _Hunk(int(m.group(1)), [], [])
                i += 1
                while i < len(lines) and not _HUNK.match(lines[i]) and not lines[i].startswith("diff --git") \
                        and not (lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")):
                    b = lines[i]
                    if b.startswith("\\"):
                        pass
                    elif b.startswith("+"):
                        h.new.append(b[1:]); h.ops.append(("+", b[1:]))
                    elif b.startswith("-"):
                        h.old.append(b[1:]); h.ops.append(("-", b[1:]))
                    elif b.startswith(" "):
                        h.old.append(b[1:]); h.new.append(b[1:]); h.ops.append((" ", b[1:]))
                    elif b == "":
                        # a blank context line whose leading space was stripped; the final empty element is just the end of the text
                        if i < len(lines) - 1 and (i + 1 < len(lines) and lines[i + 1] != "" or any(x for x in lines[i + 1:])):
                            h.old.append(""); h.new.append(""); h.ops.append((" ", ""))
                    else:
                        raise PatchError(f"unified diff line {i + 1} is malformed: {b[:60]!r} (every hunk line must start with ' ', '+' or '-')")
                    i += 1
                while h.old and h.new and h.old[-1] == "" and h.new[-1] == "" and i >= len(lines) - 1 and h.ops and h.ops[-1] == (" ", ""):
                    h.old.pop(); h.new.pop(); h.ops.pop()
                fp.hunks.append(h)
            out.append(fp)
            continue
        i += 1
    if not out:
        raise PatchError("no file sections found in the unified diff (expected '--- a/path' / '+++ b/path' / '@@' hunks)")
    return out


def _apply_hunks(text: str, hunks: list[_Hunk], path: str) -> tuple[str, bool, list[str]]:
    lines = text.split("\n")
    fuzzy, notes = False, []
    for n, h in enumerate(hunks, 1):
        expected = max(0, h.start - 1)
        if not h.old:   # pure insertion: no context to locate it, trust the line number (clamped)
            at = min(expected, len(lines) - (1 if lines and lines[-1] == "" else 0))
            lines[at:at] = h.new
            continue
        for mode, norm in (("exact", lambda s: s), ("trailing whitespace", lambda s: s.rstrip()), ("whitespace", lambda s: s.strip())):
            hits = _windows(lines, h.old, norm)
            if hits:
                break
        if not hits:
            raise PatchError(f"hunk {n} of {path} does not match the file: its context/removed lines were not found." + _closest(text, "\n".join(h.old)))
        at = min(hits, key=lambda x: abs(x - expected))
        if len(hits) > 1:
            notes.append(f"hunk {n} matched {len(hits)} places; used the one nearest line {expected + 1}")
        new = h.new
        if mode != "exact":
            # keep the file's REAL text for context lines; re-indent added lines by the drift seen on the nearest matched line
            fuzzy = True
            new, oi = [], 0
            drift = (_indent_of(next((l for l in h.old if l.strip()), "")), _indent_of(next((l for l in lines[at:at + len(h.old)] if l.strip()), "")))
            for kind, text in h.ops:
                if kind == " ":
                    new.append(lines[at + oi]); drift = (_indent_of(text), _indent_of(lines[at + oi])); oi += 1
                elif kind == "-":
                    drift = (_indent_of(text), _indent_of(lines[at + oi])); oi += 1
                else:
                    new.extend(_reindent([text], *drift) if text.strip() else [text])
            notes.append(f"hunk {n} matched ignoring {'indentation' if mode == 'whitespace' else 'trailing whitespace'} at line {at + 1}")
        lines[at:at + len(h.old)] = new
    return "\n".join(lines), fuzzy, notes


# ---- diff text ---------------------------------------------------------------------------------------------
def unified(old: str | None, new: str | None, path: str) -> tuple[str, int, int]:
    a = (old or "").split("\n") if old else []
    b = (new or "").split("\n") if new else []
    a_nl = (old or "").endswith("\n") or not old
    b_nl = (new or "").endswith("\n") or not new
    if a and a[-1] == "":
        a.pop()
    if b and b[-1] == "":
        b.pop()
    head_a = "/dev/null" if old is None else f"a/{path}"
    head_b = "/dev/null" if new is None else f"b/{path}"
    out: list[str] = []
    adds = dels = 0
    for line in difflib.unified_diff(a, b, head_a, head_b, lineterm="", n=3):
        out.append(line)
        if line.startswith("+") and not line.startswith("+++"):
            adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            dels += 1
    if not out:
        return "", 0, 0
    text = "\n".join(out) + "\n"
    if (a and not a_nl) or (b and not b_nl):   # keep git's marker so the diff round-trips
        text = text.rstrip("\n") + "\n\\ No newline at end of file\n"
    return f"diff --git a/{path} b/{path}\n" + text, adds, dels


# ---- build -------------------------------------------------------------------------------------------------
def build_patchset(root: Path, spec: PatchSpec | dict, *, fuzzy: bool = True, allow_noop: bool = False) -> PatchSet:
    spec = spec if isinstance(spec, PatchSpec) else PatchSpec.from_dict(spec)
    if spec.empty():
        raise PatchError("no changes proposed")
    ents: dict[str, _Entry] = {}

    def load(rel: str) -> _Entry:
        if rel in ents:
            return ents[rel]
        p = check_path(root, rel)
        if p.is_file():
            raw = p.read_bytes()
            text, eol, bom = _decode(raw, rel)
            ents[rel] = _Entry(True, _hash(raw), text, text, eol, bom)
        elif p.exists():
            raise PatchError(f"{rel} is not a regular file")
        else:
            ents[rel] = _Entry(False)
        return ents[rel]

    def need(rel: str) -> _Entry:
        e = load(rel)
        if not e.exists or e.deleted:
            raise PatchError(f"file not found: {rel}")
        return e

    def create(rel: str, content: str) -> None:
        e = load(rel)
        if e.exists and not e.deleted:
            raise PatchError(f"file already exists: {rel} (use edits or rewrites to change it)")
        if not isinstance(content, str):
            raise PatchError(f"new file {rel} needs string content")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise PatchError(f"new file {rel} is larger than {MAX_FILE_BYTES // 1000} KB")
        e.text, e.created, e.touched = (content if content.endswith("\n") or not content else content + "\n"), True, True
        e.deleted = False

    # 1. unified diff
    if spec.unified_diff.strip():
        for fp in parse_unified(spec.unified_diff):
            if fp.is_create:
                create(fp.new_path, "\n".join(l for h in fp.hunks for l in h.new) + "\n")
            elif fp.is_delete:
                e = need(fp.old_path)
                gone = [l for h in fp.hunks for l in h.old]
                if gone and [x.rstrip() for x in (e.text or "").rstrip("\n").split("\n")] != [x.rstrip() for x in gone]:
                    raise PatchError(f"the diff deletes {fp.old_path} but its removed lines do not match the file's content")
                e.deleted, e.touched = True, True
            else:
                e = need(fp.new_path if fp.new_path != "/dev/null" else fp.old_path)
                e.text, fz, notes = _apply_hunks(e.text or "", fp.hunks, fp.new_path)
                e.fuzzy |= fz; e.notes += notes; e.touched = True
    # 2. rewrites, 3. edits
    for rw in spec.rewrites:
        e = need(rw.get("path") or "")
        if not isinstance(rw.get("content"), str):
            raise PatchError(f"rewrite of {rw.get('path')} needs string content")
        e.text, e.touched = rw["content"], True
    for ed in spec.edits:
        f = ed.get("file")
        if not f or ed.get("search") in (None, ""):
            raise PatchError("edit is missing file/search")
        e = need(f)
        before = e.text or ""
        e.text, fz, note = apply_edit(before, ed["search"], ed.get("replace", ""), f, fuzzy)
        if e.text == before and not allow_noop:
            raise PatchError(f"edit in {f} changes nothing (`replace` equals `search`)")
        e.fuzzy |= fz; e.touched = True
        if note:
            e.notes.append(note)
    # 4. new files, 5. deletes
    for nf in spec.new_files:
        create(nf.get("path") or "", nf.get("content"))
    for rel in spec.delete_files:
        e = need(rel)
        if e.touched and not e.created:
            raise PatchError(f"{rel} is both edited and deleted in the same patch")
        e.deleted, e.touched = True, True
    if len([1 for e in ents.values() if e.deleted and e.exists]) > MAX_DELETES:
        raise PatchError(f"a patch may delete at most {MAX_DELETES} files")

    changes: list[FileChange] = []
    for rel, e in ents.items():
        if not e.touched:
            continue
        if e.created and e.deleted:
            continue
        if e.deleted:
            diff, a, d = unified(e.old, None, rel)
            changes.append(FileChange(rel, "delete", e.old, None, e.raw_hash, e.eol, e.bom, e.fuzzy, e.notes, diff, a, d))
            continue
        if e.created:
            err = syntax_error(rel, e.text or "")
            if err:
                raise PatchError(f"new file {rel} is not valid: {err}")
            diff, a, d = unified(None, e.text, rel)
            changes.append(FileChange(rel, "create", None, e.text, None, "\n", False, False, e.notes, diff, a, d))
            continue
        if e.text == e.old and not allow_noop:
            continue
        err = syntax_error(rel, e.text or "")
        if err and not syntax_error(rel, e.old or ""):
            raise PatchError(f"this change would leave {rel} with a syntax error ({err}). The original file parsed fine; fix the edit.")
        diff, a, d = unified(e.old, e.text, rel)
        changes.append(FileChange(rel, "modify", e.old, e.text, e.raw_hash, e.eol, e.bom, e.fuzzy, e.notes, diff, a, d))
    if not changes:
        raise PatchError("the patch changes nothing")
    if len(changes) > MAX_FILES:
        raise PatchError(f"a patch may touch at most {MAX_FILES} files (this one touches {len(changes)})")
    return PatchSet(changes)


# ---- apply / revert ----------------------------------------------------------------------------------------
def file_hash(root: Path, rel: str) -> str | None:
    p = safe_path(root, rel)
    return _hash(p.read_bytes()) if p.is_file() else None


def _write_atomic(p: Path, data: bytes, mode: int | None) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def apply_patchset(root: Path, ps: PatchSet, only: set[str] | None = None, verify_base: bool = True) -> dict:
    """Write the patch (all selected files or none). Returns an undo record for `revert_patchset`.
    Raises StaleError if a file changed since the patch was built."""
    sel = [c for c in ps.changes if only is None or c.path in only]
    if not sel:
        raise PatchError("no files selected")
    if verify_base:
        for c in sel:
            check_path(root, c.path)
            if file_hash(root, c.path) != c.base_hash:
                raise StaleError(f"{c.path} changed since this patch was proposed" if c.op != "create" else f"{c.path} now exists")
    undo: dict[str, dict] = {}
    done: list[str] = []
    try:
        for c in sel:
            p = check_path(root, c.path)
            if p.is_file():
                undo[c.path] = {"existed": True, "raw": base64.b64encode(p.read_bytes()).decode(), "mode": p.stat().st_mode & 0o7777}
            else:
                undo[c.path] = {"existed": False}
            if c.op == "delete":
                p.unlink()
            else:
                _write_atomic(p, _encode(c.new or "", c.eol, c.bom), undo[c.path].get("mode"))
            undo[c.path]["applied_hash"] = None if c.op == "delete" else file_hash(root, c.path)
            done.append(c.path)
    except BaseException:
        _restore(root, {k: undo[k] for k in done + ([c.path for c in sel if c.path in undo and c.path not in done])})
        raise
    return undo


def _restore(root: Path, undo: dict[str, dict]) -> None:
    for rel, u in undo.items():
        p = safe_path(root, rel)
        if u["existed"]:
            _write_atomic(p, base64.b64decode(u["raw"]), u.get("mode"))
        elif p.exists():
            p.unlink()
            d = p.parent
            while d != root and d.is_dir() and not any(d.iterdir()):
                d.rmdir(); d = d.parent


def revert_patchset(root: Path, undo: dict[str, dict], force: bool = False) -> list[str]:
    """Put the files back as they were before `apply_patchset`. Refuses (StaleError) if they were edited since, unless force."""
    if not force:
        for rel, u in undo.items():
            if file_hash(root, rel) != u.get("applied_hash"):
                raise StaleError(f"{rel} was modified after the patch was applied; reverting would discard those edits")
    _restore(root, undo)
    return list(undo)
