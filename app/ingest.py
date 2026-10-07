from __future__ import annotations
import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from .parsing.chunker import chunk_file
from .parsing.deps import parse_package_json, parse_requirements, python_imports
from .retrieval.embeddings import get_embedder
from .retrieval.index import CodeIndex

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", ".idea",
             ".pytest_cache", ".mypy_cache", "site-packages", "target"}
TEXT_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".md", ".txt",
            ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sql", ".html", ".css", ".sh", ".env.example"}
TEXT_NAMES = {"Dockerfile", "requirements.txt", "Makefile"}
MAX_BYTES = 500_000


def iter_source_files(root: Path):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            p = Path(dirpath) / f
            if (p.suffix.lower() in TEXT_EXT or f in TEXT_NAMES) and p.stat().st_size <= MAX_BYTES:
                yield p.relative_to(root).as_posix(), p


def build_index(root: Path, embedder=None) -> CodeIndex:
    embedder = embedder or get_embedder()
    chunks, tree, imports = [], [], {}
    deps = {"requirements": [], "node": []}
    for rel, p in iter_source_files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        tree.append(rel)
        chunks += chunk_file(rel, text)
        if rel.endswith(".py"):
            imports[rel] = python_imports(text)
        elif rel.endswith("requirements.txt"):
            deps["requirements"] += parse_requirements(text)
        elif rel.endswith("package.json"):
            deps["node"] += parse_package_json(text)
    return CodeIndex.build(chunks, tree, deps, imports, embedder)


_URL = re.compile(r"^https://[\w.-]+/[\w.\-]+/[\w.\-]+(\.git)?/?$")


def clone_repo(url: str, dest: Path) -> None:
    if not _URL.match(url):
        raise ValueError("only https://host/owner/repo URLs are accepted")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise ValueError(f"git clone failed: {r.stderr.strip()[:300]}")


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
