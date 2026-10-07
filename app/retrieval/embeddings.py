from __future__ import annotations
import zlib
import numpy as np
from ..config import get_settings
from ..utils import tokenize


class HashingEmbedder:
    """Dependency-free feature-hashing embedder (token + bigram). Works offline; mostly lexical.
    Swap for OpenAI/Gemini embeddings for real semantic search."""

    name = "hash"
    dim = 512

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = tokenize(t[:8000])
            for tok in toks:
                h = zlib.crc32(tok.encode())
                out[i, h % self.dim] += 1.0 if (h >> 16) & 1 else -1.0
            for a, b in zip(toks, toks[1:]):
                h = zlib.crc32(f"{a} {b}".encode())
                out[i, h % self.dim] += 0.5 if (h >> 16) & 1 else -0.5
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


class OpenAIEmbedder:
    name = "openai"

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        from openai import OpenAI

        self.client, self.model = OpenAI(api_key=api_key), model

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = []
        for i in range(0, len(texts), 64):
            r = self.client.embeddings.create(model=self.model, input=[t[:6000] or " " for t in texts[i : i + 64]])
            vecs += [d.embedding for d in r.data]
        a = np.array(vecs, dtype=np.float32)
        return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-9)


class GeminiEmbedder:
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-embedding-001") -> None:
        from google import genai

        self.client, self.model = genai.Client(api_key=api_key), model

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = []
        for i in range(0, len(texts), 64):
            r = self.client.models.embed_content(model=self.model, contents=[t[:6000] or " " for t in texts[i : i + 64]])
            vecs += [e.values for e in r.embeddings]
        a = np.array(vecs, dtype=np.float32)
        return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-9)


def get_embedder(provider: str | None = None):
    s = get_settings()
    provider = (provider or s.embedding_provider).lower()
    if provider == "hash":
        return HashingEmbedder()
    if provider == "openai":
        return OpenAIEmbedder(s.openai_api_key)
    if provider == "gemini":
        return GeminiEmbedder(s.gemini_api_key)
    raise ValueError(f"unknown embedding provider: {provider}")
