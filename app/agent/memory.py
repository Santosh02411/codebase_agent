"""Conversation memory: what was asked and found earlier in a conversation, kept small.

Recent turns are rendered nearly verbatim, older ones as one line each, all under a token budget. Persisted per conversation id so
follow-ups ("now fix it", "why does that fail?") can be resolved against the previous answer after a server restart."""
from __future__ import annotations
import json
import re
import threading
import time
import uuid
from pathlib import Path

from ..rag.context import estimate_tokens

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def new_conversation_id() -> str:
    return uuid.uuid4().hex[:16]


class ConversationStore:
    def __init__(self, base: Path | None = None, max_turns: int = 30) -> None:
        self.base = base
        self.max_turns = max_turns
        self._mem: dict[str, list[dict]] = {}
        self._lock = threading.Lock()
        if base is not None:
            base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def valid(cid: str | None) -> bool:
        return bool(cid) and bool(_ID.match(cid or ""))

    def turns(self, cid: str | None) -> list[dict]:
        if not self.valid(cid):
            return []
        with self._lock:
            if cid in self._mem:
                return list(self._mem[cid])
            if self.base is not None and (self.base / f"{cid}.json").is_file():
                try:
                    self._mem[cid] = json.loads((self.base / f"{cid}.json").read_text())
                except (ValueError, OSError):
                    self._mem[cid] = []
                return list(self._mem[cid])
        return []

    def append(self, cid: str | None, turn: dict) -> None:
        if not self.valid(cid):
            return
        cur = self.turns(cid)
        cur.append({"ts": time.time(), **turn})
        cur = cur[-self.max_turns:]
        with self._lock:
            self._mem[cid] = cur
            if self.base is not None:
                try:
                    (self.base / f"{cid}.json").write_text(json.dumps(cur, indent=1))
                except OSError:
                    pass

    def clear(self, cid: str) -> None:
        with self._lock:
            self._mem.pop(cid, None)
            if self.base is not None and self.valid(cid):
                (self.base / f"{cid}.json").unlink(missing_ok=True)

    def last_files(self, cid: str | None) -> list[str]:
        t = self.turns(cid)
        return list(t[-1].get("files", [])) if t else []

    def render(self, cid: str | None, recent: int = 4, budget: int = 900) -> str:
        """History block for prompts: '' when there is none."""
        turns = self.turns(cid)
        if not turns:
            return ""
        lines: list[str] = []
        older, last = turns[:-recent], turns[-recent:]
        for t in older:
            lines.append(f"- earlier: {t.get('question', '')[:100]} → {t.get('status', '')}" + (f" ({', '.join(t.get('files', [])[:2])})" if t.get("files") else ""))
        for t in last:
            files = f" [files: {', '.join(t['files'][:4])}]" if t.get("files") else ""
            lines.append(f"- user: {t.get('question', '')[:300]}\n  agent ({t.get('status', '')}){files}: {t.get('summary', '')[:400]}")
        while len(lines) > 1 and estimate_tokens("\n".join(lines)) > budget:
            lines.pop(0)   # drop the oldest first
        return "\n".join(lines)
