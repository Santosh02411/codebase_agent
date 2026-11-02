"""What gets indexed for a chunk. Shared by the in-memory index and the PostgreSQL store so both see identical text."""
from __future__ import annotations
import hashlib

from ..parsing.chunker import Chunk
from ..utils import tokenize


def chunk_tokens(c: Chunk) -> list[str]:
    """Tokens for keyword search: identifier-aware, over path + symbol + route + code."""
    return tokenize(f"{c.file} {c.qualname} {c.route} {c.text}")


def embed_text(c: Chunk) -> str:
    """Text sent to the embedding model."""
    return f"{c.file}\n{c.qualname}\n{c.route}\n{c.doc}\n{c.text}"


def content_hash(c: Chunk) -> str:
    return hashlib.sha1(embed_text(c).encode()).hexdigest()
