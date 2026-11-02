"""Compatibility shim: embedding providers now live in app/rag/embedders.py."""
from ..rag.embedders import (  # noqa: F401
    Embedder, EmbeddingError, FastEmbedEmbedder, GeminiEmbedder, HashingEmbedder, OpenAIEmbedder, SentenceTransformerEmbedder,
    get_embedder, normalize,
)
