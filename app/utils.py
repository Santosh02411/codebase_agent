from __future__ import annotations
import re
from pathlib import Path

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def split_identifier(s: str) -> list[str]:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s).replace("_", " ").lower().split()


_SUFFIXES = ("ation", "ate", "ing", "ed", "es", "s")


def stem(tok: str) -> str:
    """Tiny suffix stemmer so `authentication` matches `authenticate_user`."""
    if tok.endswith("ies") and len(tok) > 5:
        return tok[:-3] + "y"
    for suf in _SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def tokenize(text: str) -> list[str]:
    """Identifier-aware tokenizer: `calculateDeliveryEta` -> whole identifier + parts (+ stems)."""
    toks: list[str] = []
    for m in _IDENT.findall(text):
        parts = [m.lower()] + (split_identifier(m) if len(split_identifier(m)) > 1 else [])
        for p in parts:
            toks.append(p)
            sp = stem(p)
            if sp != p:
                toks.append(sp)
    return toks


def safe_path(root: Path, rel: str) -> Path:
    """Resolve `rel` inside `root`, refusing path traversal."""
    p = (root / rel).resolve()
    if root.resolve() != p and root.resolve() not in p.parents:
        raise ValueError(f"path escapes repository: {rel}")
    return p
