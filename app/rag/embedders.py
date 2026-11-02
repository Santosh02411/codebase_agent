"""Embedding providers behind one interface.

    embed_documents(texts) -> (n, dim) float32, L2-normalised     (used when indexing code)
    embed_query(text)      -> (dim,)   float32, L2-normalised     (used when searching; asymmetric models need this)

A model is selected with a spec string, so experiments can name any combination:
    hash                                   offline feature hashing (baseline, no semantics)
    openai:text-embedding-3-small[:512]    OpenAI (or any OpenAI-compatible server via OPENAI_BASE_URL: Ollama, vLLM, TEI, LM Studio)
    gemini:gemini-embedding-001[:768]      Google Gemini (RETRIEVAL_DOCUMENT / CODE_RETRIEVAL_QUERY task types)
    bge:BAAI/bge-small-en-v1.5             local sentence-transformers model (BGE, E5, Jina, ...), needs `pip install sentence-transformers`
    fastembed:BAAI/bge-small-en-v1.5       local ONNX model, needs `pip install fastembed` (no PyTorch)
"""
from __future__ import annotations
import re
import time
import zlib
from typing import Callable

import httpx
import numpy as np

from ..config import get_settings
from ..utils import tokenize


class EmbeddingError(RuntimeError):
    pass


def _client() -> httpx.Client:  # tests replace this with a MockTransport client
    return httpx.Client(timeout=60)


_sleep: Callable[[float], None] = time.sleep  # tests replace this so retries are instant


def normalize(a: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=np.float32)
    if a.ndim == 1:
        return a / max(float(np.linalg.norm(a)), 1e-9)
    return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-9)


def _truncate(text: str, max_chars: int) -> str:
    return (text[:max_chars] if text.strip() else " ")


def post_json(url: str, headers: dict, payload: dict, retries: int = 5, what: str = "embedding API") -> dict:
    """POST with exponential backoff on 429 / 5xx / network errors. Never puts the API key in an error message."""
    delay = 1.0
    last = ""
    for attempt in range(retries + 1):
        try:
            with _client() as c:
                r = c.post(url, headers=headers, json=payload)
        except httpx.HTTPError as e:
            last = f"network error: {type(e).__name__}"
        else:
            if r.status_code < 300:
                return r.json()
            try:
                msg = r.json().get("error", {})
                msg = msg.get("message") if isinstance(msg, dict) else str(msg)
            except ValueError:
                msg = r.text[:200]
            last = f"{r.status_code}: {(msg or r.reason_phrase)[:300]}"
            if r.status_code not in (408, 409, 429, 500, 502, 503, 504):
                raise EmbeddingError(f"{what} rejected the request ({last})")
            ra = r.headers.get("retry-after")
            if ra and ra.replace(".", "", 1).isdigit():
                delay = max(delay, min(float(ra), 60.0))
        if attempt < retries:
            _sleep(delay)
            delay = min(delay * 2, 30.0)
    raise EmbeddingError(f"{what} failed after {retries + 1} attempts ({last})")


class Embedder:
    """Base class. Subclasses implement `_embed(texts, is_query)`."""

    provider = ""
    model = ""
    dim = 0
    batch_size = 64
    max_chars = 6000

    def __init__(self) -> None:
        self.usage  # noqa: B018 - touch the lazy property

    @property
    def usage(self) -> dict:
        """Calls, texts, tokens (when the API reports them) and wall-clock seconds spent embedding. Created lazily so that
        subclasses that don't call super().__init__() keep working."""
        return self.__dict__.setdefault("_usage", {"calls": 0, "texts": 0, "tokens": 0, "seconds": 0.0})

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}" + (f":{self.dim}" if self.provider in ("openai", "gemini") and self.dim else "")

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def _run(self, texts: list[str], is_query: bool) -> np.ndarray:
        t0 = time.time()
        out = []
        for i in range(0, len(texts), self.batch_size):
            batch = [_truncate(t, self.max_chars) for t in texts[i:i + self.batch_size]]
            self.usage["calls"] += 1
            out.append(self._embed(batch, is_query))
        self.usage["texts"] += len(texts)
        self.usage["seconds"] += time.time() - t0
        if not out:
            return np.zeros((0, self.dim or 1), dtype=np.float32)
        arr = normalize(np.vstack(out))
        if not self.dim:
            self.dim = arr.shape[1]
        return arr

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._run(texts, False)

    def embed_query(self, text: str) -> np.ndarray:
        return self._run([text], True)[0]

    # Backwards-compatible alias used by the index builder
    def embed(self, texts: list[str]) -> np.ndarray:
        return self.embed_documents(texts)


class HashingEmbedder(Embedder):
    """Dependency-free feature hashing (token + bigram). Works offline; lexical, not semantic. The experiment baseline."""

    provider, model, dim = "hash", "", 512

    @property
    def name(self) -> str:
        return "hash"

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = tokenize(t[:8000])
            for tok in toks:
                h = zlib.crc32(tok.encode())
                out[i, h % self.dim] += 1.0 if (h >> 16) & 1 else -1.0
            for a, b in zip(toks, toks[1:]):
                h = zlib.crc32(f"{a} {b}".encode())
                out[i, h % self.dim] += 0.5 if (h >> 16) & 1 else -0.5
        return out


class OpenAIEmbedder(Embedder):
    """OpenAI `/v1/embeddings` (text-embedding-3-small/large support `dimensions`). Works with any OpenAI-compatible server."""

    provider = "openai"
    max_chars = 8000

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dim: int | None = None,
                 base_url: str = "https://api.openai.com/v1") -> None:
        super().__init__()
        if not api_key and "api.openai.com" in base_url:
            raise EmbeddingError("OPENAI_API_KEY is not set")
        self.api_key, self.model, self.base_url = api_key, model, base_url.rstrip("/")
        self.requested_dim = dim
        self.dim = dim or {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}.get(model, 0)

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        payload: dict = {"model": self.model, "input": texts}
        if self.requested_dim:
            payload["dimensions"] = self.requested_dim
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = post_json(f"{self.base_url}/embeddings", headers, payload, what="OpenAI embeddings")
        rows = sorted(data["data"], key=lambda d: d["index"])
        if len(rows) != len(texts):
            raise EmbeddingError(f"embedding API returned {len(rows)} vectors for {len(texts)} inputs")
        self.usage["tokens"] += int((data.get("usage") or {}).get("total_tokens", 0))
        return np.array([r["embedding"] for r in rows], dtype=np.float32)


class GeminiEmbedder(Embedder):
    """Gemini `batchEmbedContents`. Documents and queries use different task types; gemini-embedding-001 has a code-specific
    query type. Dimensions below the model's native size must be re-normalised (done here)."""

    provider = "gemini"
    batch_size = 100
    max_chars = 8000
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str, model: str = "gemini-embedding-001", dim: int | None = None, code_queries: bool = True) -> None:
        super().__init__()
        if not api_key:
            raise EmbeddingError("GEMINI_API_KEY is not set")
        self.api_key, self.model, self.requested_dim = api_key, model.removeprefix("models/"), dim
        self.dim = dim or {"gemini-embedding-001": 3072, "text-embedding-004": 768}.get(self.model, 0)
        self.code_queries = code_queries and self.model == "gemini-embedding-001"

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        task = ("CODE_RETRIEVAL_QUERY" if self.code_queries else "RETRIEVAL_QUERY") if is_query else "RETRIEVAL_DOCUMENT"
        reqs = []
        for t in texts:
            r: dict = {"model": f"models/{self.model}", "content": {"parts": [{"text": t}]}, "taskType": task}
            if self.requested_dim:
                r["outputDimensionality"] = self.requested_dim
            reqs.append(r)
        data = post_json(f"{self.BASE}/models/{self.model}:batchEmbedContents", {"x-goog-api-key": self.api_key}, {"requests": reqs},
                         what="Gemini embeddings")
        embs = data.get("embeddings") or []
        if len(embs) != len(texts):
            raise EmbeddingError(f"embedding API returned {len(embs)} vectors for {len(texts)} inputs")
        return np.array([e["values"] for e in embs], dtype=np.float32)


# prefix conventions of popular open models: (query prefix, document prefix)
_PREFIXES = {
    "bge-small-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "bge-base-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "bge-large-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "bge-m3": ("", ""),
    "e5": ("query: ", "passage: "),
    "nomic-embed": ("search_query: ", "search_document: "),
}


def _prefixes_for(model: str) -> tuple[str, str]:
    low = model.lower()
    for key, v in _PREFIXES.items():
        if key in low:
            return v
    return ("", "")


class SentenceTransformerEmbedder(Embedder):
    """Local model through sentence-transformers (BGE, E5, Jina, Nomic, ...). Runs on CPU or GPU, no API cost."""

    provider = "bge"
    batch_size = 32
    max_chars = 4000

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", device: str | None = None, trust_remote_code: bool = False) -> None:
        super().__init__()
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise EmbeddingError("local embeddings need `pip install sentence-transformers`") from e
        self.model = model
        self.q_prefix, self.d_prefix = _prefixes_for(model)
        self._m = SentenceTransformer(model, device=device, trust_remote_code=trust_remote_code)
        self.dim = int(self._m.get_sentence_embedding_dimension() or 0)

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        prefix = self.q_prefix if is_query else self.d_prefix
        v = self._m.encode([prefix + t for t in texts], batch_size=self.batch_size, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(v, dtype=np.float32)


class FastEmbedEmbedder(Embedder):
    """Local ONNX model through fastembed (small install, no PyTorch)."""

    provider = "fastembed"
    batch_size = 32
    max_chars = 4000

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        super().__init__()
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise EmbeddingError("local ONNX embeddings need `pip install fastembed`") from e
        self.model = model
        self.q_prefix, self.d_prefix = _prefixes_for(model)
        self._m = TextEmbedding(model_name=model)
        self.dim = len(next(iter(self._m.embed(["dimension probe"]))))

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        prefix = self.q_prefix if is_query else self.d_prefix
        return np.array(list(self._m.embed([prefix + t for t in texts], batch_size=self.batch_size)), dtype=np.float32)


_CACHE: dict[str, Embedder] = {}


def parse_spec(spec: str) -> tuple[str, str, int | None]:
    """'openai:text-embedding-3-small:512' -> ('openai', 'text-embedding-3-small', 512). Model ids may contain '/' and ':'-free text."""
    spec = (spec or "hash").strip()
    provider, _, rest = spec.partition(":")
    dim = None
    m = re.match(r"^(.*):(\d+)$", rest)
    if m:
        rest, dim = m.group(1), int(m.group(2))
    return provider.lower(), rest, dim


def get_embedder(spec: str | None = None, *, cache: bool = True) -> Embedder:
    """Embedder for a spec string (default: the server's EMBEDDING_* settings). Local models are cached: loading is slow."""
    s = get_settings()
    if spec is None:
        provider, model, dim = s.embedding_provider, s.embedding_model, s.embedding_dim or None
        spec = f"{provider}:{model}" + (f":{dim}" if dim else "") if model else provider
    provider, model, dim = parse_spec(spec)
    key = f"{provider}:{model}:{dim}"
    if cache and key in _CACHE:
        return _CACHE[key]
    if provider == "hash":
        e: Embedder = HashingEmbedder()
    elif provider == "openai":
        e = OpenAIEmbedder(s.openai_api_key, model or "text-embedding-3-small", dim, s.openai_base_url)
    elif provider == "gemini":
        e = GeminiEmbedder(s.gemini_api_key, model or "gemini-embedding-001", dim)
    elif provider in ("bge", "st", "sentence-transformers", "local"):
        e = SentenceTransformerEmbedder(model or "BAAI/bge-small-en-v1.5")
    elif provider == "fastembed":
        e = FastEmbedEmbedder(model or "BAAI/bge-small-en-v1.5")
    else:
        raise EmbeddingError(f"unknown embedding provider: {provider!r} (use hash, openai, gemini, bge or fastembed)")
    if cache and provider not in ("openai", "gemini"):
        _CACHE[key] = e
    return e
