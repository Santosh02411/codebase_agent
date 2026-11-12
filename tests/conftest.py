import shutil
from pathlib import Path
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "delivery_sync"


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    # a developer's real .env (e.g. LLM_PROVIDER=gemini) must never leak into tests
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    # the suite runs repository fixtures directly; the Docker sandbox is exercised separately (tests/test_sandbox_exec.py, with a fake `docker`)
    monkeypatch.setenv("SANDBOX_MODE", "local")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("FAST_PLANNING", "false")      # the scripted-model tests exercise the planning calls; test_fast_planning.py covers the fast path
    from app import ratelimit
    ratelimit.reset()


@pytest.fixture
def repo(tmp_path):
    dest = tmp_path / "delivery_sync"
    shutil.copytree(FIXTURE, dest)
    return dest


@pytest.fixture
def tools(repo):
    from app.agent.tools import RepoTools
    from app.ingest import build_index
    return RepoTools(repo, build_index(repo), test_timeout=60)
