"""Incremental indexing: only files whose content hash changed are re-parsed, only new chunk texts are re-embedded."""
from __future__ import annotations
import json
import pickle
import posixpath
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

import numpy as np

from .chunks import chunks_for
from .extract import extract_file, sha1
from .graph import CodeGraph
from .manifests import go_module, parse_manifest
from .model import EXTRACTOR_VERSION, FileFacts

Progress = Callable[[str, int, int], None]


@dataclass
class IndexReport:
    mode: str = "full"            # full | incremental
    files_total: int = 0
    files_added: int = 0
    files_changed: int = 0
    files_removed: int = 0
    files_unchanged: int = 0
    chunks_total: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0
    duration_ms: int = 0
    changed_files: list[str] = field(default_factory=list)
    parsers: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


class IndexBuilder:
    def __init__(self, root: Path, embedder, cache_dir: Path | None = None, progress: Progress | None = None) -> None:
        self.root, self.embedder, self.cache_dir = root, embedder, cache_dir
        self.progress = progress or (lambda *_: None)

    def build(self):
        from ..ingest import iter_source_files  # late import: ingest imports this module
        from ..retrieval.index import CodeIndex

        t0 = time.time()
        report = IndexReport()
        facts_cache: dict[str, dict] = {}
        emb_cache: dict[str, np.ndarray] = {}
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cached = _load_json(self.cache_dir / "facts.json")
            if cached.get("version") == EXTRACTOR_VERSION:
                facts_cache = cached.get("files", {})
            try:
                with open(self.cache_dir / "embeddings.pkl", "rb") as f:
                    e = pickle.load(f)
                if e.get("embedder") == self.embedder.name:
                    emb_cache = e.get("vecs", {})
            except (OSError, pickle.PickleError, EOFError):
                pass
        report.mode = "incremental" if facts_cache else "full"

        self.progress("scanning", 0, 0)
        entries: list[tuple[str, bytes]] = []
        for rel, p in iter_source_files(self.root):
            try:
                data = p.read_bytes()
                data.decode("utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            entries.append((rel, data))

        facts: dict[str, FileFacts] = {}
        texts: dict[str, str] = {}
        manifest_deps: dict[str, set] = {}
        manifest_files: list[str] = []
        gomod, go_root = "", ""
        for i, (rel, data) in enumerate(entries, 1):
            self.progress("parsing", i, len(entries))
            digest = sha1(data)
            cached_f = facts_cache.get(rel)
            if cached_f and cached_f.get("hash") == digest:
                f = FileFacts.from_dict(cached_f)
                report.files_unchanged += 1
            else:
                f = extract_file(rel, data)
                report.files_changed += 1 if cached_f else 0
                report.files_added += 0 if cached_f else 1
                report.changed_files.append(rel)
            facts[rel] = f
            text = data.decode("utf-8")
            texts[rel] = text
            m = parse_manifest(rel, text)
            if m:
                manifest_deps.setdefault(m[0], set()).update(m[1])
                manifest_files.append(rel)
            if rel.endswith("go.mod") and not gomod:
                gomod, go_root = go_module(text), posixpath.dirname(rel)
        report.files_removed = len(set(facts_cache) - set(facts))
        report.files_total = len(facts)
        if report.mode == "incremental" and report.files_added + report.files_changed + report.files_removed == 0:
            report.mode = "incremental"
        parsers: dict[str, int] = {}
        for f in facts.values():
            parsers[f.parser or "none"] = parsers.get(f.parser or "none", 0) + 1
        report.parsers = parsers

        self.progress("graph", 0, 0)
        context = {"go_module": gomod, "go_root": go_root}
        graph = CodeGraph(facts, context)

        chunks = []
        for rel, f in facts.items():
            chunks += chunks_for(f, texts[rel])
        for i, c in enumerate(chunks):
            c.id = i
        report.chunks_total = len(chunks)

        keys = [sha1(f"{c.file}\n{c.qualname}\n{c.route}\n{c.doc}\n{c.text}".encode()) for c in chunks]
        embed_texts = {k: f"{c.file}\n{c.qualname}\n{c.route}\n{c.doc}\n{c.text}" for k, c in zip(keys, chunks)}
        missing = [k for k in dict.fromkeys(keys) if k not in emb_cache]
        report.chunks_embedded = len(missing)
        report.chunks_reused = len(set(keys)) - len(missing)
        for start in range(0, len(missing), 64):
            batch = missing[start:start + 64]
            self.progress("embedding", start, len(missing))
            vecs = self.embedder.embed([embed_texts[k] for k in batch])
            for k, v in zip(batch, vecs):
                emb_cache[k] = v
        self.progress("embedding", len(missing), len(missing))
        emb = np.vstack([emb_cache[k] for k in keys]).astype(np.float32) if keys else np.zeros((0, 1), dtype=np.float32)

        deps = {"requirements": sorted(manifest_deps.get("python", ())), "node": sorted(manifest_deps.get("node", ())),
                **{k: sorted(v) for k, v in manifest_deps.items() if k not in ("python", "node")}, "files": manifest_files}
        deps["python"] = deps["requirements"]
        imports = {p: sorted({i.module for i in f.imports if i.module and i.level == 0}) for p, f in facts.items() if f.language == "python"}
        index = CodeIndex(chunks, emb, sorted(facts), deps, imports, self.embedder.name, self.embedder, facts=facts, graph=graph,
                          context=context)

        if self.cache_dir:
            self.progress("saving", 0, 0)
            (self.cache_dir / "facts.json").write_text(json.dumps({"version": EXTRACTOR_VERSION, "files": {p: f.to_dict() for p, f in facts.items()}}))
            live = set(keys)
            with open(self.cache_dir / "embeddings.pkl", "wb") as f:
                pickle.dump({"embedder": self.embedder.name, "vecs": {k: v for k, v in emb_cache.items() if k in live}}, f)
        report.duration_ms = int((time.time() - t0) * 1000)
        index.report = report.to_dict()
        self.progress("ready", 1, 1)
        return index
