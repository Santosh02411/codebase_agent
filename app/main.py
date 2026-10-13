from __future__ import annotations
import itertools
import json
import os
import queue
import threading
import time
import uuid

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import features, github_pr, gitops, instrument, patching, terminal, textsearch
from .agent.graph import run_agent
from .agent.nodes import AgentRuntime
from .agent.state import new_state
from .agent.tools import RepoTools
from .config import get_settings
from .llm import get_llm
from .services import RepoService
from .utils import safe_path

app = FastAPI(title="AI Codebase Intelligence & Debugging Agent", version="0.4.0")
_service: RepoService | None = None
STATIC = Path(__file__).parent / "static"
# The Next.js IDE (frontend/) runs on another port in development, so allow it to call this API.
app.add_middleware(CORSMiddleware, allow_methods=["*"], allow_headers=["*"],
                   allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()])
app.mount("/static", StaticFiles(directory=STATIC), name="static")


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


def _run(body: AskIn, allow_fix: bool, allow_verify: bool = True, emit=None) -> dict:
    s = get_settings()
    _, root, index = _repo(body.repo_id)
    try:
        llm = get_llm(body.provider)
        tools = RepoTools(root, index, s.test_timeout)
        rt = AgentRuntime(llm, tools, s)
        if emit:
            instrument.instrument(rt, llm, tools, emit)
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


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "llm_provider": s.llm_provider, "embedding_provider": s.embedding_provider,
            "llm_model": s.llm_model, "github_configured": bool(s.github_token), "git_available": gitops.available(),
            "allow_local_paths": s.allow_local_paths}


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


@app.get("/repositories/{repo_id}/file")
def read_file(repo_id: str, path: str):
    """Return one source file (for the UI code viewer). Paths are confined to the repository."""
    _, root, _ = _repo(repo_id)
    try:
        text = safe_path(root, path).read_text(encoding="utf-8")  # exact text, incl. trailing newline
    except UnicodeDecodeError:
        raise HTTPException(400, "this file is not text, so it can't be shown")
    except (ValueError, OSError):
        raise HTTPException(400, f"can't read {path}")
    return {"path": path, "text": text[:200_000], "truncated": len(text) > 200_000}


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


# ---- v4: architecture, review, code changes, test generation, pull requests ----------------------
class RepoOnly(BaseModel):
    repo_id: str
    provider: str | None = None


class ReviewIn(RepoOnly):
    path: str | None = None


class ChangeIn(RepoOnly):
    request: str
    verify: bool = True


class TestsIn(RepoOnly):
    target: str  # file path, e.g. services/eta.py
    verify: bool = True


class ChangesIn(BaseModel):
    repo_id: str
    edits: list[dict] = []
    new_files: list[dict] = []


class PRIn(BaseModel):
    repo_id: str
    files: dict[str, str]  # path -> full new content (the `final_files` of a /change response)
    title: str
    body: str = ""
    confirm: bool = False


def _feature(repo_id: str, provider: str | None, fn, emit=None):
    s = get_settings()
    _, root, index = _repo(repo_id)
    try:
        llm, tools = get_llm(provider), RepoTools(root, index, s.test_timeout)
        if emit:
            instrument.instrument(None, llm, tools, emit)
        return fn(llm, tools, s)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"agent failed: {type(e).__name__}: {e}")


@app.post("/architecture")
def architecture(body: RepoOnly):
    """Explain how the project is structured and how its parts connect."""
    return _feature(body.repo_id, body.provider, lambda llm, t, s: features.architecture(llm, t))


@app.post("/review")
def review(body: ReviewIn):
    """Code review of one file or the whole project: automatic checks plus AI findings."""
    return _feature(body.repo_id, body.provider, lambda llm, t, s: features.review(llm, t, body.path))


@app.post("/change")
def change(body: ChangeIn):
    """Generate code / modify several files for a request; tests run before and after in a sandbox copy."""
    return _feature(body.repo_id, body.provider, lambda llm, t, s: features.change_code(llm, t, s, body.request, body.verify))


@app.post("/generate-tests")
def generate_tests(body: TestsIn):
    """Write a new test file for a source file and run it in the sandbox."""
    return _feature(body.repo_id, body.provider, lambda llm, t, s: features.generate_tests(llm, t, s, body.target, body.verify))


@app.post("/apply-changes")
def apply_changes(body: ChangesIn):
    """Apply an approved multi-file change to the working copy, then re-index."""
    _, root, _ = _repo(body.repo_id)
    try:
        files = patching.apply_changes(root, body.edits, body.new_files)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"files": files, "index": service().reindex(body.repo_id)}


@app.post("/create-pr")
def create_pr(body: PRIn):
    """Open a GitHub pull request with an approved change. Needs GITHUB_TOKEN and confirm=true."""
    if not body.confirm:
        raise HTTPException(400, "confirm must be true: this creates a branch and a pull request on GitHub")
    meta, root, _ = _repo(body.repo_id)
    try:
        for path in body.files:
            safe_path(root, path)
        return github_pr.create_pr(meta["source"], get_settings().github_token, body.files, body.title, body.body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"GitHub request failed: {type(e).__name__}: {e}")


# ---- v5: IDE endpoints (symbols, text search, git, terminal, live agent stream) --------------------
@app.get("/repositories/{repo_id}/symbols")
def symbols(repo_id: str, path: str | None = None, q: str | None = None, limit: int = 200):
    """Functions, methods and classes: of one file (`path`) or across the repository (`q` filters by name)."""
    return textsearch.symbols(_repo(repo_id)[2], path, q, min(limit, 1000))


class SaveIn(BaseModel):
    path: str
    text: str


@app.put("/repositories/{repo_id}/file")
def save_file(repo_id: str, body: SaveIn):
    """Save an edit made in the IDE editor to the server's working copy (never your original folder), then re-index."""
    _, root, _ = _repo(repo_id)
    try:
        p = safe_path(root, body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not p.is_file():
        raise HTTPException(400, f"file not found: {body.path}")
    if len(body.text) > 2_000_000:
        raise HTTPException(400, "file too large to save from the editor")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(body.text)
    return service().reindex(repo_id)


@app.get("/repositories/{repo_id}/grep")
def grep(repo_id: str, q: str, regex: bool = False, case: bool = False, limit: int = 300):
    """Exact text / regex search over every indexed file."""
    _, root, index = _repo(repo_id)
    try:
        return textsearch.grep(root, index.tree, q, regex, case, min(limit, 1000))
    except ValueError as e:
        raise HTTPException(400, str(e))


def _git_call(fn, *a):
    try:
        return fn(*a)
    except (gitops.GitError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.get("/repositories/{repo_id}/git/status")
def git_status(repo_id: str):
    return _git_call(gitops.status, _repo(repo_id)[1])


@app.get("/repositories/{repo_id}/git/file")
def git_file(repo_id: str, path: str):
    """Original (HEAD) and current text of one file, for the diff viewer."""
    return _git_call(gitops.file_versions, _repo(repo_id)[1], path)


class PathIn(BaseModel):
    repo_id: str
    path: str


class CommitIn(BaseModel):
    repo_id: str
    message: str


@app.post("/git/discard")
def git_discard(body: PathIn):
    _git_call(gitops.discard, _repo(body.repo_id)[1], body.path)
    service().reindex(body.repo_id)
    return gitops.status(_repo(body.repo_id)[1])


@app.post("/git/commit")
def git_commit(body: CommitIn):
    return _git_call(gitops.commit, _repo(body.repo_id)[1], body.message)


class TerminalIn(BaseModel):
    repo_id: str
    command: str


@app.post("/terminal/exec")
def terminal_exec(body: TerminalIn):
    _, root, index = _repo(body.repo_id)
    return terminal.execute(root, index, body.command, get_settings().test_timeout)


class StreamIn(BaseModel):
    repo_id: str
    mode: Literal["chat", "debug", "fix", "change", "tests", "review", "architecture"]
    text: str = ""            # question, error report or change request
    target: str | None = None  # file for tests / review
    provider: str | None = None
    verify: bool = True


@app.post("/agent/stream")
def agent_stream(body: StreamIn):
    """Run the agent and stream what it does (tool calls, model calls, steps) as server-sent events,
    ending with one `result` event. Same results as /chat, /debug, /change, ... but observable live."""
    _repo(body.repo_id)  # 404 early
    q: queue.Queue = queue.Queue()
    counter = itertools.count(1)
    emitted_steps = [0]

    def emit(ev: dict) -> None:
        if ev.get("type") == "step":
            emitted_steps[0] += 1
        q.put({"seq": next(counter), "ts": time.time(), **ev})

    def work() -> None:
        try:
            emit({"type": "run_start", "mode": body.mode})
            ask = AskIn(repo_id=body.repo_id, question=body.text, provider=body.provider)
            m = body.mode
            if m == "chat":
                res = _run(ask, False, emit=emit)
            elif m == "debug":
                res = _run(ask, True, True, emit=emit)
            elif m == "fix":
                res = _run(ask, True, False, emit=emit)
            elif m == "change":
                res = _feature(body.repo_id, body.provider, lambda llm, t, s: features.change_code(llm, t, s, body.text, body.verify), emit)
            elif m == "tests":
                res = _feature(body.repo_id, body.provider, lambda llm, t, s: features.generate_tests(llm, t, s, body.target or body.text, body.verify), emit)
            elif m == "review":
                res = _feature(body.repo_id, body.provider, lambda llm, t, s: features.review(llm, t, body.target or None), emit)
            else:
                res = _feature(body.repo_id, body.provider, lambda llm, t, s: features.architecture(llm, t), emit)
            if not emitted_steps[0]:  # features that only report steps at the end
                for st in res.get("steps", []):
                    emit({"type": "step", **st})
            q.put({"seq": next(counter), "ts": time.time(), "type": "result", "mode": m, "data": res})
        except HTTPException as e:
            q.put({"seq": next(counter), "ts": time.time(), "type": "error", "message": str(e.detail)})
        except Exception as e:  # noqa: BLE001 - surface anything to the UI
            q.put({"seq": next(counter), "ts": time.time(), "type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while True:
            try:
                ev = q.get(timeout=15)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if ev is None:
                break
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
