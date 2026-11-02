from __future__ import annotations
import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from . import gitops, providers
from .intel.store import IndexBuilder
from .retrieval.embeddings import get_embedder

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", ".idea",
             ".pytest_cache", ".mypy_cache", "site-packages", "target"}
TEXT_EXT = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".go", ".rs", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".md", ".txt",
            ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sql", ".html", ".css", ".sh", ".env.example"}
TEXT_NAMES = {"Dockerfile", "requirements.txt", "Makefile", "pom.xml", "build.gradle", "build.gradle.kts", "go.mod"}
MAX_BYTES = 500_000


def iter_source_files(root: Path):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            p = Path(dirpath) / f
            if (p.suffix.lower() in TEXT_EXT or f in TEXT_NAMES) and p.stat().st_size <= MAX_BYTES:
                yield p.relative_to(root).as_posix(), p


def build_index(root: Path, embedder=None, cache_dir: Path | None = None, progress=None):
    """Parse every file into symbols + graphs and index it. With `cache_dir`, only changed files are reprocessed."""
    return IndexBuilder(root, embedder or get_embedder(), cache_dir, progress).build()


def clone_repo(url: str, dest: Path, branch: str | None = None, auth_header: str | None = None) -> None:
    """Shallow clone that still knows every branch (so you can switch later). Credentials go via the environment only."""
    url = providers.validate_url(url)
    cmd = ["git", "clone", "--depth", "1", "--no-single-branch", "-q"]
    if branch:
        cmd += ["--branch", gitops._check_ref(branch)]
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **gitops.net_env(auth_header)}
    try:
        r = subprocess.run(cmd + [url, str(dest)], capture_output=True, text=True, timeout=300, env=env)
    except FileNotFoundError:
        raise ValueError("git is not installed on the server")
    except subprocess.TimeoutExpired:
        raise ValueError("git clone timed out")
    if r.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        tail = (r.stderr.strip().splitlines() or ["clone failed"])[-1]
        raise ValueError(f"git clone failed: {tail[:300]}")


def copy_local(src: Path, dest: Path) -> None:
    if not src.is_dir():
        raise ValueError(f"not a directory: {src}")
    src, dest = src.resolve(), dest.resolve()
    if dest.exists():
        shutil.rmtree(dest)
    # If the destination lives inside the source (e.g. you add this very project and DATA_DIR=./data),
    # copying would recurse into its own output forever. Skip every folder on the path to dest.
    guarded = {a for a in dest.parents if src in a.parents}

    def ignore(directory: str, names: list[str]) -> set[str]:
        skip = {n for n in names if n in SKIP_DIRS}
        skip |= {n for n in names if (Path(directory) / n).resolve() in guarded}
        return skip

    shutil.copytree(src, dest, ignore=ignore)


def extract_zip(fileobj, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(fileobj.read())) as z:
        for m in z.infolist():
            target = (dest / m.filename).resolve()
            if dest.resolve() not in target.parents and target != dest.resolve():
                raise ValueError("unsafe path in zip")
        z.extractall(dest)
    entries = [p for p in dest.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():  # unwrap single top-level folder
        inner = entries[0]
        for p in inner.iterdir():
            shutil.move(str(p), dest / p.name)
        inner.rmdir()
