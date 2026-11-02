"""Experiments as a service: list datasets, run benchmarks in a background thread, browse saved results."""
from __future__ import annotations
import json
import re
import threading
import time
import uuid
from pathlib import Path

from .eval.dataset import load_dataset
from .eval.runner import ExpConfig, preset_configs, run_experiment, save_result

DATASET_DIR = Path(__file__).resolve().parents[2] / "eval" / "datasets"
_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")


def list_datasets() -> list[dict]:
    out = []
    for p in sorted(DATASET_DIR.glob("*.jsonl")):
        try:
            ds = load_dataset(p)
        except ValueError:
            continue
        out.append({"name": p.stem, "questions": len(ds.questions), "description": ds.meta.get("description", ""), "repo": ds.meta.get("repo", "")})
    return out


def dataset_path(name: str) -> Path:
    if not _NAME.match(name) or not (DATASET_DIR / f"{name}.jsonl").is_file():
        raise ValueError(f"unknown dataset: {name!r}")
    return DATASET_DIR / f"{name}.jsonl"


class Experiments:
    """One experiment at a time (they are CPU- and API-cost heavy). Results are JSON files under <data_dir>/experiments."""

    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir / "experiments"
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def list(self) -> list[dict]:
        out = []
        for p in sorted(self.dir.glob("*.json"), reverse=True):
            try:
                r = json.loads(p.read_text())
            except ValueError:
                continue
            ok = [c for c in r["configs"] if c["status"] == "ok"]
            best = max(ok, key=lambda c: c["summary"]["symbol"]["mrr"]["mean"], default=None)
            out.append({"id": r["id"], "created": r["created"], "dataset": r["dataset"]["name"], "questions": r["dataset"]["questions"],
                        "store": r["store"], "configs": len(r["configs"]), "skipped": len(r["configs"]) - len(ok),
                        "best": {"name": best["config"]["name"], "mrr": best["summary"]["symbol"]["mrr"]["mean"]} if best else None})
        return out

    def get(self, exp_id: str) -> dict:
        if not _NAME.match(exp_id) or not (self.dir / f"{exp_id}.json").is_file():
            raise KeyError(exp_id)
        return json.loads((self.dir / f"{exp_id}.json").read_text())

    def start(self, root: Path, dataset: str, spec: dict, store=None, repo_label: str = "") -> str:
        """spec: {"preset": "offline"} | {"embedders": [...], "rerankers": [...]} | {"configs": [ {...ExpConfig fields} ]}, plus "ks"."""
        path = dataset_path(dataset)
        ds = load_dataset(path)
        if spec.get("configs"):
            configs = [ExpConfig.from_dict(c) for c in spec["configs"]]
        elif spec.get("embedders"):
            configs = preset_configs([e for e in spec["embedders"] if e], [r for r in spec.get("rerankers", []) if r])
        else:
            configs = preset_configs(["hash"], ["heuristic"])
        if not configs:
            raise ValueError("no configurations to run")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("an experiment is already running")
        job_id = uuid.uuid4().hex[:10]
        job = {"id": job_id, "state": "running", "phase": "starting", "done": 0, "total": 0, "started": time.time(), "dataset": dataset, "result_id": None, "error": ""}
        self.jobs[job_id] = job

        def progress(phase: str, i: int, n: int) -> None:
            job.update(phase=phase, done=i, total=n)

        def work() -> None:
            try:
                res = run_experiment(root, ds, configs, ks=tuple(spec.get("ks") or (1, 3, 5, 10)), store=store, progress=progress,
                                     repo_id=f"eval-{job_id}")
                res["repo"] = repo_label or res["repo"]
                save_result(res, self.dir)
                job.update(state="done", result_id=res["id"], phase="done")
            except Exception as e:  # noqa: BLE001
                job.update(state="error", error=f"{type(e).__name__}: {e}"[:400])
            finally:
                self._lock.release()
        threading.Thread(target=work, daemon=True).start()
        return job_id
