from __future__ import annotations
import json
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import patching
from .agent.graph import run_agent
from .agent.nodes import AgentRuntime
from .agent.state import new_state
from .agent.tools import RepoTools
from .config import get_settings
from .llm import get_llm
from .services import RepoService

app = FastAPI(title="AI Codebase Intelligence & Debugging Agent", version="0.1.0")
_service: RepoService | None = None


def service() -> RepoService:
    global _service
    s = get_settings()
    if _service is None or _service.s.data_dir != s.data_dir:
        _service = RepoService(s)
    return _service


class RepoIn(BaseModel):
    source: str  # GitHub https URL (or local path when ALLOW_LOCAL_PATHS=true)
    name: str | None = None


class SearchIn(BaseModel):
    repo_id: str
    query: str
    k: int = 5


class AskIn(BaseModel):
    repo_id: str
    question: str  # a question, or an error message / stack trace for /debug
    provider: str | None = None


class EditIn(BaseModel):
    repo_id: str
    file: str
    search: str
    replace: str


def _repo(repo_id: str):
    try:
        return service().get(repo_id)
    except KeyError:
        raise HTTPException(404, f"unknown repository: {repo_id}")


def _run(body: AskIn, allow_fix: bool, allow_verify: bool = True) -> dict:
    s = get_settings()
    _, root, index = _repo(body.repo_id)
    try:
        llm = get_llm(body.provider)
        rt = AgentRuntime(llm, RepoTools(root, index, s.test_timeout), s)
        st = run_agent(rt, new_state(body.question, body.repo_id, allow_fix, allow_verify))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # provider / network failures
        raise HTTPException(502, f"agent failed: {type(e).__name__}: {e}")
    run_id = uuid.uuid4().hex[:12]
    out = {"run_id": run_id, "llm": llm.name, "status": st["status"], "answer": st["answer"], "intent": st["intent"],
           "analysis": st["analysis"], "patch": st["edit"], "diff": st["diff"], "test_before": st["test_before"],
           "test_after": st["test_after"], "steps": st["steps"],
           "sources": [{"file": c["file"], "lines": f"{c['start']}-{c['end']}", "symbol": c["qualname"]} for c in st["context"]]}
    runs = s.data_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(json.dumps(out, indent=2))
    return out


@app.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "llm_provider": s.llm_provider, "embedding_provider": s.embedding_provider}


@app.post("/repositories")
def add_repository(body: RepoIn):
    try:
        return service().add(body.source, body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/repositories/upload")
def upload_repository(file: UploadFile = File(...), name: str = Form("uploaded-project")):
    try:
        return service().add_zip(file.file, name)
    except Exception as e:
        raise HTTPException(400, f"could not import zip: {e}")


@app.get("/repositories")
def list_repositories():
    return service().list()


@app.post("/repositories/{repo_id}/index")
def reindex(repo_id: str):
    _repo(repo_id)
    return service().reindex(repo_id)


@app.get("/repositories/{repo_id}/tree")
def tree(repo_id: str):
    return {"files": _repo(repo_id)[2].tree}


@app.post("/search")
def search(body: SearchIn):
    _, root, index = _repo(body.repo_id)
    return RepoTools(root, index).search_code(body.query, k=body.k)


@app.post("/chat")
def chat(body: AskIn):
    """Ask about the codebase. Retrieval + reasoning only — never modifies code."""
    return _run(body, allow_fix=False)


@app.post("/debug")
def debug(body: AskIn):
    """Full loop: analyse → retrieve → root cause → patch → run tests before/after → report."""
    return _run(body, allow_fix=True, allow_verify=True)


@app.post("/generate-fix")
def generate_fix(body: AskIn):
    """Analyse and propose a patch without running tests."""
    return _run(body, allow_fix=True, allow_verify=False)


@app.post("/run-tests")
def run_tests(body: dict):
    _, root, index = _repo(body.get("repo_id", ""))
    return RepoTools(root, index, get_settings().test_timeout).run_tests()


@app.post("/apply-patch")
def apply_patch(body: EditIn):
    """Apply an approved edit to the working copy of the repository (the 'Apply Fix' button)."""
    _, root, _ = _repo(body.repo_id)
    try:
        patching.apply_edit(root, body.model_dump(include={"file", "search", "replace"}))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return service().reindex(body.repo_id)


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    p = get_settings().data_dir / "runs" / f"{run_id}.json"
    if not p.is_file() or not run_id.isalnum():
        raise HTTPException(404, "unknown run")
    return json.loads(p.read_text())
