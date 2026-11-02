from __future__ import annotations
import hashlib
import json
import re
import threading
import time
from collections import defaultdict
from pathlib import Path

from . import auth, gitops, ingest, providers
from .config import Settings
from .intel.stats import repo_stats
from .retrieval.embeddings import get_embedder
from .retrieval.index import CodeIndex, StaleIndex


class RepoService:
    """Repository registry, per-repo index cache and incremental (re)indexing.
    v1 = JSON file + pickled indexes + a per-repo cache of parsed files and embeddings (PostgreSQL in Phase 7)."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.repos_dir = settings.data_dir / "repos"
        self.idx_dir = settings.data_dir / "indexes"
        self.meta_path = settings.data_dir / "repos.json"
        for d in (self.repos_dir, self.idx_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, CodeIndex] = {}
        self._status: dict[str, dict] = {}
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._meta_lock = threading.Lock()
        self.auth = auth.AuthStore(settings.data_dir)

    # ---- registry -----------------------------------------------------------------------------
    def _meta(self) -> dict:
        return json.loads(self.meta_path.read_text()) if self.meta_path.exists() else {}

    def _save_meta(self, m: dict) -> None:
        self.meta_path.write_text(json.dumps(m, indent=2))

    @staticmethod
    def _slug(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "repo"

    @staticmethod
    def _is_remote(source: str) -> bool:
        return source.startswith("https://")

    def _header_for(self, source: str) -> str | None:
        provider = providers.provider_of(source)
        return providers.auth_header(provider, self.s, self.auth.token("github") if provider == "github" else None)

    # ---- import -------------------------------------------------------------------------------
    def preview(self, source: str) -> dict:
        """Branches of a remote repository before importing it."""
        url = providers.validate_url(source)
        info = gitops.ls_remote_heads(url, self._header_for(url))
        return {"provider": providers.provider_of(url), "name": providers.display_name(url), **info}

    def add(self, source: str, name: str | None = None, branch: str | None = None) -> dict:
        name = name or source.rstrip("/").split("/")[-1].removesuffix(".git")
        repo_id = f"{self._slug(name)}-{hashlib.sha1(source.encode()).hexdigest()[:6]}"
        dest = self.repos_dir / repo_id
        provider = "local"
        if self._is_remote(source):
            provider = providers.provider_of(source)
            self._set_status(repo_id, state="indexing", phase="cloning", done=0, total=0)
            try:
                ingest.clone_repo(source, dest, branch, self._header_for(source))
            except ValueError:
                self._status.pop(repo_id, None)
                raise
        elif self.s.allow_local_paths:
            ingest.copy_local(Path(source).expanduser(), dest)
        else:
            raise ValueError("local paths are disabled (set ALLOW_LOCAL_PATHS=true) — use a repository URL or zip upload")
        return self._index(repo_id, name, source, dest, provider=provider)

    def add_zip(self, fileobj, name: str) -> dict:
        repo_id = f"{self._slug(name)}-{hashlib.sha1(f'zip:{name}'.encode()).hexdigest()[:6]}"
        dest = self.repos_dir / repo_id
        ingest.extract_zip(fileobj, dest)
        return self._index(repo_id, name, f"upload:{name}", dest, provider="upload")

    # ---- indexing -----------------------------------------------------------------------------
    def _set_status(self, repo_id: str, **kw) -> None:
        cur = self._status.get(repo_id, {})
        self._status[repo_id] = {**cur, **kw, "updated": time.time()}

    def status_of(self, repo_id: str) -> dict:
        if repo_id in self._status:
            return dict(self._status[repo_id])
        return {"state": "ready"} if repo_id in self._meta() else {"state": "unknown"}

    def all_status(self) -> dict[str, dict]:
        return {rid: dict(st) for rid, st in self._status.items()}

    def _index(self, repo_id: str, name: str, source: str, root: Path, provider: str | None = None) -> dict:
        lock = self._locks[repo_id]
        if not lock.acquire(blocking=False):
            raise ValueError("this repository is already being indexed")
        try:
            self._set_status(repo_id, state="indexing", phase="scanning", done=0, total=0, started=time.time(), error="")
            try:
                gitops.ensure_repo(root)  # baseline commit so the IDE can show Git changes
            except gitops.GitError:
                pass

            def progress(phase: str, done: int, total: int) -> None:
                self._set_status(repo_id, phase=phase, done=done, total=total)

            try:
                index = ingest.build_index(root, get_embedder(self.s.embedding_provider), self.idx_dir / repo_id, progress)
                index.save(self.idx_dir / f"{repo_id}.pkl")
            except Exception as e:  # noqa: BLE001
                self._set_status(repo_id, state="error", phase="failed", error=f"{type(e).__name__}: {e}"[:300])
                raise
            self._cache[repo_id] = index
            head = gitops.head_info(root)
            langs = sorted({f.language for f in index.facts.values() if f.symbols})
            with self._meta_lock:
                m = self._meta()
                old = m.get(repo_id, {})
                meta = {"id": repo_id, "name": name, "source": source, "files": len(index.tree), "chunks": len(index.chunks),
                        "embedder": index.embedder_name, "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "provider": provider or old.get("provider", "local"), "branch": head["branch"], "commit": head["commit"],
                        "detached": head["detached"], "languages": langs, "symbols": len(index.graph.symbols), "last_index": index.report}
                m[repo_id] = meta
                self._save_meta(m)
            self._set_status(repo_id, state="ready", phase="ready", done=1, total=1, report=index.report)
            return meta
        finally:
            lock.release()

    def reindex(self, repo_id: str) -> dict:
        meta, root, _ = self._get_meta_root(repo_id)
        return self._index(repo_id, meta["name"], meta["source"], root)

    # ---- access -------------------------------------------------------------------------------
    def _get_meta_root(self, repo_id: str) -> tuple[dict, Path, None]:
        meta = self._meta().get(repo_id)
        if not meta:
            raise KeyError(repo_id)
        return meta, self.repos_dir / repo_id, None

    def list(self) -> list[dict]:
        return list(self._meta().values())

    def get(self, repo_id: str) -> tuple[dict, Path, CodeIndex]:
        meta = self._meta().get(repo_id)
        if not meta:
            raise KeyError(repo_id)
        if repo_id not in self._cache:
            try:
                self._cache[repo_id] = CodeIndex.load(self.idx_dir / f"{repo_id}.pkl")
            except (StaleIndex, FileNotFoundError, KeyError, EOFError):
                meta = self._index(repo_id, meta["name"], meta["source"], self.repos_dir / repo_id)  # saved index is from an older version
        return meta, self.repos_dir / repo_id, self._cache[repo_id]

    def stats(self, repo_id: str) -> dict:
        meta, root, index = self.get(repo_id)
        head = gitops.head_info(root)
        st = repo_stats(index)
        st["repo"] = {"id": repo_id, "name": meta["name"], "source": meta["source"], "provider": meta.get("provider", ""),
                      "branch": head["branch"], "commit": head["commit"], "detached": head["detached"]}
        st["indexing"] = {**self.status_of(repo_id), "indexed_at": meta.get("indexed_at"), "embedder": index.embedder_name,
                          "chunks": len(index.chunks), "last_index": index.report or meta.get("last_index", {})}
        return st

    # ---- branches / commits -------------------------------------------------------------------
    def branches(self, repo_id: str) -> dict:
        _, root, _ = self._get_meta_root(repo_id)
        return gitops.branches(root)

    def commits(self, repo_id: str, ref: str | None, limit: int, skip: int) -> list[dict]:
        _, root, _ = self._get_meta_root(repo_id)
        return gitops.commits(root, ref, limit, skip)

    def checkout(self, repo_id: str, ref: str, force: bool = False) -> dict:
        """Switch branch/commit, then re-index incrementally: only files that differ between the two are reprocessed."""
        meta, root, _ = self._get_meta_root(repo_id)
        gitops.checkout(root, ref, force)
        return self._index(repo_id, meta["name"], meta["source"], root)

    def fetch(self, repo_id: str, deepen: int = 50) -> dict:
        meta, root, _ = self._get_meta_root(repo_id)
        return gitops.fetch(root, deepen, self._header_for(meta["source"]) if self._is_remote(meta["source"]) else None)
