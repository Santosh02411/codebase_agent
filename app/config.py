from __future__ import annotations
import os
from pathlib import Path

try:  # load .env automatically (real environment variables win)
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # python-dotenv is optional
    pass


class Settings:
    """Runtime configuration, read from environment variables (see .env.example)."""

    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
        self.llm_provider = os.getenv("LLM_PROVIDER", "mock")  # mock | gemini | openai
        self.llm_model = os.getenv("LLM_MODEL", "")
        self.embedding_provider = os.getenv("EMBEDDING_PROVIDER", "hash")  # hash | openai | gemini
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.allow_local_paths = os.getenv("ALLOW_LOCAL_PATHS", "false").lower() == "true"
        self.max_agent_steps = int(os.getenv("MAX_AGENT_STEPS", "3"))
        self.max_fix_attempts = int(os.getenv("MAX_FIX_ATTEMPTS", "2"))
        self.test_timeout = int(os.getenv("TEST_TIMEOUT", "120"))
        self.github_token = os.getenv("GITHUB_TOKEN", "")  # only needed for pull requests
        # GitHub OAuth app (optional): https://github.com/settings/developers -> callback = <backend>/auth/github/callback
        self.github_client_id = os.getenv("GITHUB_CLIENT_ID", "")
        self.github_client_secret = os.getenv("GITHUB_CLIENT_SECRET", "")
        self.github_scope = os.getenv("GITHUB_OAUTH_SCOPE", "repo read:user")
        self.oauth_redirect_base = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000").rstrip("/")
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
        # Optional personal access tokens for private GitLab / Bitbucket repositories (OAuth for these is planned)
        self.gitlab_token = os.getenv("GITLAB_TOKEN", "")
        self.bitbucket_username = os.getenv("BITBUCKET_USERNAME", "")
        self.bitbucket_app_password = os.getenv("BITBUCKET_APP_PASSWORD", "")
        # ---- RAG pipeline ----
        self.database_url = os.getenv("DATABASE_URL", "")            # postgresql://user:pass@host/db  -> chunks + vectors in PostgreSQL/pgvector
        self.database_schema = os.getenv("DATABASE_SCHEMA", "")        # optional: keep this app's tables in their own schema
        self.rag_store = os.getenv("RAG_STORE", "auto").lower()      # auto (pgvector if DATABASE_URL is set) | memory | pgvector
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "")
        self.embedding_dim = int(os.getenv("EMBEDDING_DIM", "0") or 0)
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.reranker = os.getenv("RERANKER", "heuristic")           # none | heuristic | bge-reranker-base | cross-encoder:<model> | llm
        self.retrieval_mode = os.getenv("RETRIEVAL_MODE", "hybrid")  # hybrid | vector | keyword
        self.rrf_k = int(os.getenv("RRF_K", "60"))
        # Weight of the vector leg in hybrid fusion. Unset = automatic: 0.25 for the lexical hashing baseline (measured: equal
        # weights are worse than BM25 alone, see eval/), 1.0 for real embedding models. Re-tune for yours with `python -m app.rag.eval`.
        self.vector_weight = float(os.environ["VECTOR_WEIGHT"]) if os.getenv("VECTOR_WEIGHT") else None
        self.keyword_weight = float(os.getenv("KEYWORD_WEIGHT", "1.0"))
        self.retrieval_candidates = int(os.getenv("RETRIEVAL_CANDIDATES", "50"))
        self.context_token_budget = int(os.getenv("CONTEXT_TOKEN_BUDGET", "6000"))
        self.max_context_chunks = int(os.getenv("MAX_CONTEXT_CHUNKS", "12"))


def get_settings() -> Settings:
    return Settings()
