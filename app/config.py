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
        self.max_context_chunks = int(os.getenv("MAX_CONTEXT_CHUNKS", "12"))


def get_settings() -> Settings:
    return Settings()
