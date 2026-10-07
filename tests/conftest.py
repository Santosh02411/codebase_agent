import shutil
from pathlib import Path
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "delivery_sync"


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
