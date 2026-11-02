"""Evaluation datasets.

One JSON object per line (JSONL):
    {"id": "q1", "question": "where is the delivery ETA calculated?",
     "relevant": [{"file": "services/eta.py", "symbol": "calculate_delivery_eta"}],     # symbol is optional (file-level label)
     "tags": ["locate"], "notes": "free text"}
`relevant` may also give `lines: [start, end]` for code that has no symbol (config, docs). The first line may be
    {"_meta": {"name": "...", "repo": "...", "description": "..."}}
Paths are relative to the repository root that is indexed. Every label is checked against the index by `validate`."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Expected:
    file: str
    symbol: str | None = None
    lines: tuple[int, int] | None = None

    def to_dict(self) -> dict:
        d: dict = {"file": self.file}
        if self.symbol:
            d["symbol"] = self.symbol
        if self.lines:
            d["lines"] = list(self.lines)
        return d


@dataclass
class Question:
    id: str
    question: str
    relevant: list[Expected]
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "question": self.question, "relevant": [e.to_dict() for e in self.relevant]}
        if self.tags:
            d["tags"] = self.tags
        if self.notes:
            d["notes"] = self.notes
        return d


@dataclass
class Dataset:
    name: str
    questions: list[Question]
    meta: dict = field(default_factory=dict)

    def save(self, path: Path) -> None:
        lines = [json.dumps({"_meta": {"name": self.name, **self.meta}})] + [json.dumps(q.to_dict()) for q in self.questions]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")


def _expected(d: dict) -> Expected:
    lines = d.get("lines")
    return Expected(d["file"], d.get("symbol") or None, (int(lines[0]), int(lines[1])) if lines else None)


def load_dataset(path: str | Path) -> Dataset:
    path = Path(path)
    meta: dict = {}
    questions: list[Question] = []
    text = path.read_text()
    if path.suffix == ".json":  # the original eval/dataset.json: [{"question", "expected_files"}]
        for i, d in enumerate(json.loads(text), 1):
            questions.append(Question(d.get("id", f"q{i}"), d["question"], [Expected(f) for f in d["expected_files"]]))
        return Dataset(path.stem, questions)
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            d = json.loads(line)
        except ValueError as e:
            raise ValueError(f"{path}:{n}: invalid JSON ({e})")
        if "_meta" in d:
            meta = d["_meta"]
            continue
        try:
            questions.append(Question(d.get("id") or f"q{len(questions) + 1}", d["question"], [_expected(r) for r in d["relevant"]],
                                      list(d.get("tags", [])), d.get("notes", "")))
        except KeyError as e:
            raise ValueError(f"{path}:{n}: missing field {e}")
    return Dataset(meta.pop("name", path.stem), questions, meta)


def validate(ds: Dataset, index) -> list[str]:
    """Problems that would silently corrupt a benchmark: stale paths/symbols, empty or duplicate questions."""
    problems: list[str] = []
    seen: set[str] = set()
    files = set(index.tree)
    symbols: dict[str, set[str]] = {}
    for c in index.chunks:
        if c.kind != "module":          # module-level code has no symbol name; label such targets by file (or line range)
            symbols.setdefault(c.file, set()).add(c.qualname)
    for q in ds.questions:
        if q.id in seen:
            problems.append(f"{q.id}: duplicate id")
        seen.add(q.id)
        if not q.question.strip():
            problems.append(f"{q.id}: empty question")
        if not q.relevant:
            problems.append(f"{q.id}: no relevant items")
        for e in q.relevant:
            if e.file not in files:
                problems.append(f"{q.id}: file not in the repository: {e.file}")
            elif e.symbol and e.symbol not in symbols.get(e.file, set()):
                near = sorted(symbols.get(e.file, set()))[:6]
                problems.append(f"{q.id}: no symbol {e.symbol!r} in {e.file} (found: {', '.join(near) or 'none'})")
    return problems
