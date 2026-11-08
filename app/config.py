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
        # ---- code execution sandbox (everything that runs repository code goes through app/sandbox_exec.py) ----
        # docker (default): each run is a throw-away container: no network, CPU/memory/pid limits, read-only root, tmpfs, no capabilities, non-root.
        # local: runs on THIS machine with rlimits only. Not isolated. For a developer's own laptop and the test-suite, never for a public server.
        self.sandbox_mode = os.getenv("SANDBOX_MODE", "docker").lower()
        self.sandbox_cpus = float(os.getenv("SANDBOX_CPUS", "1.0"))
        self.sandbox_memory_mb = int(os.getenv("SANDBOX_MEMORY_MB", "1024"))
        self.sandbox_pids = int(os.getenv("SANDBOX_PIDS", "256"))
        self.sandbox_tmpfs_mb = int(os.getenv("SANDBOX_TMPFS_MB", "256"))
        self.sandbox_output_limit = int(os.getenv("SANDBOX_OUTPUT_LIMIT", "1000000"))      # bytes of stdout+stderr kept per run
        self.sandbox_network = os.getenv("SANDBOX_NETWORK", "none").lower()                  # none | bridge (not recommended)
        self.sandbox_images = {lang: os.getenv(f"SANDBOX_IMAGE_{lang.upper()}", f"codebase-agent/sandbox-{lang}:latest") for lang in ("python", "node", "go", "rust", "java")}
        self.sandbox_install_deps = os.getenv("SANDBOX_INSTALL_DEPS", "false").lower() in ("1", "true", "yes")   # a separate networked step; no install scripts are run
        self.sandbox_audit_network = os.getenv("SANDBOX_AUDIT_NETWORK", "false").lower() in ("1", "true", "yes")  # lets pip-audit / npm audit reach their advisory databases
        self.sandbox_max_concurrent = int(os.getenv("SANDBOX_MAX_CONCURRENT", "2"))            # containers running at once, server-wide; others wait in line
        self.sandbox_queue_timeout = float(os.getenv("SANDBOX_QUEUE_TIMEOUT", "120"))          # seconds a run may wait for a slot before it is refused as busy
        self.rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "0"))              # per client, on the endpoints that start agents / run code; 0 = off
        self.sandbox_cache_dir = Path(os.getenv("SANDBOX_CACHE_DIR", "")) if os.getenv("SANDBOX_CACHE_DIR") else None
        # ---- LLM layer ----
        self.llm_fast_model = os.getenv("LLM_MODEL_FAST", "")          # cheaper model for planning / tool selection (falls back to LLM_MODEL)
        self.llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
        self.llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT", "30"))
        self.llm_max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
        # skip the two planning model calls for plain questions (Explain mode): the research step already chooses the tools. Set FAST_PLANNING=false to always plan with the model.
        self.fast_planning = os.getenv("FAST_PLANNING", "true").lower() not in ("0", "false", "no")
        self.llm_fallback = os.getenv("LLM_FALLBACK", "")             # "provider[:model]", tried when the primary keeps failing
        self.llm_prices = os.getenv("LLM_PRICES", "")                 # optional JSON {"model": [usd_per_1M_input, usd_per_1M_output]}
        self.max_llm_calls = int(os.getenv("MAX_LLM_CALLS", "40"))     # hard cap per agent run
        # ---- optional web search tool (off unless a provider key is set) ----
        self.web_search_provider = os.getenv("WEB_SEARCH_PROVIDER", "").lower()   # "brave" | "tavily"; default: whichever key is set
        self.brave_api_key = os.getenv("BRAVE_API_KEY", "")
        self.tavily_api_key = os.getenv("TAVILY_API_KEY", "")
        # ---- agent ----
        self.max_test_runs = int(os.getenv("MAX_TEST_RUNS", "4"))        # test runs the model may trigger itself, per agent run
        self.max_tool_calls = int(os.getenv("MAX_TOOL_CALLS", "10"))   # tool calls per research round
        self.max_tool_iterations = int(os.getenv("MAX_TOOL_ITERATIONS", "5"))  # model turns per research round
        self.max_agent_total_steps = int(os.getenv("MAX_AGENT_TOTAL_STEPS", "40"))
        self.max_run_seconds = int(os.getenv("MAX_RUN_SECONDS", "900"))   # wall-clock limit for one agent run (0 = none)
        self.history_turns = int(os.getenv("HISTORY_TURNS", "4"))
        self.history_token_budget = int(os.getenv("HISTORY_TOKEN_BUDGET", "900"))


def get_settings() -> Settings:
    return Settings()
