"""Token, latency and (optional) cost accounting. One tracker per LLM instance (= per agent run) plus a process-wide one."""
from __future__ import annotations
import json
import threading
import time
from dataclasses import asdict, dataclass, field


@dataclass
class CallRecord:
    task: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False
    latency_ms: int = 0
    ok: bool = True
    error: str = ""
    attempts: int = 1
    fallback: bool = False
    ts: float = field(default_factory=time.time)


def parse_prices(raw: str) -> dict[str, tuple[float, float]]:
    """LLM_PRICES='{"model-name": [usd_per_1M_input_tokens, usd_per_1M_output_tokens]}'. Nothing is hard-coded: prices change."""
    if not raw:
        return {}
    try:
        return {k: (float(v[0]), float(v[1])) for k, v in json.loads(raw).items()}
    except (ValueError, TypeError, KeyError, IndexError):
        return {}


class UsageTracker:
    def __init__(self, keep: int = 200, prices: dict | None = None, parent: "UsageTracker | None" = None) -> None:
        self._lock = threading.Lock()
        self.records: list[CallRecord] = []
        self.keep = keep
        self.prices = prices or {}
        self.parent = parent
        self._count = 0

    def record(self, rec: CallRecord) -> None:
        with self._lock:
            self._count += 1
            self.records.append(rec)
            if len(self.records) > self.keep:
                del self.records[: len(self.records) - self.keep]
        if self.parent is not None:
            self.parent.record(rec)

    @property
    def calls(self) -> int:
        return self._count

    def _cost(self, rec: CallRecord) -> float | None:
        p = self.prices.get(rec.model)
        return None if p is None else (rec.input_tokens * p[0] + rec.output_tokens * p[1]) / 1_000_000

    def summary(self) -> dict:
        with self._lock:
            recs = list(self.records)
        by_task: dict[str, dict] = {}
        by_model: dict[str, dict] = {}
        cost, priced = 0.0, False
        for r in recs:
            for key, bucket in ((r.task, by_task), (r.model, by_model)):
                b = bucket.setdefault(key, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0})
                b["calls"] += 1; b["input_tokens"] += r.input_tokens; b["output_tokens"] += r.output_tokens; b["latency_ms"] += r.latency_ms
            c = self._cost(r)
            if c is not None:
                cost += c; priced = True
        lat = sorted(r.latency_ms for r in recs)
        out = {
            "calls": len(recs), "failed_calls": sum(1 for r in recs if not r.ok),
            "input_tokens": sum(r.input_tokens for r in recs), "output_tokens": sum(r.output_tokens for r in recs),
            "total_tokens": sum(r.input_tokens + r.output_tokens for r in recs),
            "estimated_tokens": any(r.estimated for r in recs),
            "latency_ms": sum(lat), "avg_latency_ms": int(sum(lat) / len(lat)) if lat else 0,
            "p95_latency_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else 0,
            "retries": sum(1 for r in recs if r.attempts > 1 and not r.fallback), "fallbacks": sum(1 for r in recs if r.fallback),
            "by_task": by_task, "by_model": by_model,
        }
        if priced:
            out["cost_usd"] = round(cost, 6)
        return out

    def recent(self, n: int = 50) -> list[dict]:
        with self._lock:
            return [asdict(r) for r in self.records[-n:]]


GLOBAL_USAGE = UsageTracker(keep=500)   # whole-process totals, served by GET /llm/usage
