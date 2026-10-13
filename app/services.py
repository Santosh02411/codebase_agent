from __future__ import annotations
import hashlib
import json
import re
import time
from pathlib import Path

from . import gitops, ingest
from .config import Settings
from .retrieval.embeddings import get_embedder
from .retrieval.index import CodeIndex


class RepoService:
    """Repository registry + index cache. v1 = JSON file + pickled indexes (PostgreSQL in Phase 7)."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.repos_dir = settings.data_dir / "repos"
        self.idx_dir = settings.data_dir / "indexes"
        self.meta_path = settings.data_dir / "repos.json"
        for d in (self.repos_dir, self.idx_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, CodeIndex] = {}

    def _meta(self) -> dict:
        return json.loads(self.meta_path.read_text()) if self.meta_path.exists() else {}

    def _save_meta(self, m: dict) -> None:
        self.meta_path.write_text(json.dumps(m, indent=2))

    @staticmethod
    def _slug(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "repo"

    def add(self, source: str, name: str | None = None) -> dict:
        name = name or source.rstrip("/").split("/")[-1].removesuffix(".git")
        repo_id = f"{self._slug(name)}-{hashlib.sha1(source.encode()).hexdigest()[:6]}"
        dest = self.repos_dir / repo_id
        if source.startswith("https://"):
            ingest.clone_repo(source, dest)
        elif self.s.allow_local_paths:
            ingest.copy_local(Path(source).expanduser(), dest)
        else:
            raise ValueError("local paths are disabled (set ALLOW_LOCAL_PATHS=true) — use a GitHub URL or zip upload")
        return self._index(repo_id, name, source, dest)

    def add_zip(self, fileobj, name: str) -> dict:
        repo_id = f"{self._slug(name)}-{hashlib.sha1(f'zip:{name}'.encode()).hexdigest()[:6]}"
        dest = self.repos_dir / repo_id
        ingest.extract_zip(fileobj, dest)
        return self._index(repo_id, name, f"upload:{name}", dest)

    def _index(self, repo_id: str, name: str, source: str, root: Path) -> dict:
        try:
            gitops.ensure_repo(root)  # baseline commit so the IDE can show Git changes
        except gitops.GitError:
            pass
        index = ingest.build_index(root, get_embedder(self.s.embedding_provider))
        index.save(self.idx_dir / f"{repo_id}.pkl")
        self._cache[repo_id] = index
        meta = {"id": repo_id, "name": name, "source": source, "files": len(index.tree),
                "chunks": len(index.chunks), "embedder": index.embedder_name,
                "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        m = self._meta(); m[repo_id] = meta; self._save_meta(m)
        return meta

    def reindex(self, repo_id: str) -> dict:
        meta, root, _ = self.get(repo_id)
        return self._index(repo_id, meta["name"], meta["source"], root)

    def list(self) -> list[dict]:
        return list(self._meta().values())

    def get(self, repo_id: str) -> tuple[dict, Path, CodeIndex]:
        meta = self._meta().get(repo_id)
        if not meta:
            raise KeyError(repo_id)
        if repo_id not in self._cache:
            self._cache[repo_id] = CodeIndex.load(self.idx_dir / f"{repo_id}.pkl")
        return meta, self.repos_dir / repo_id, self._cache[repo_id]
