"""Synthetic evaluation questions: ask an LLM to write the question a developer would ask whose answer is a given function.
Cheap way to get hundreds of labelled examples on your own repository. Caveats: questions can still leak vocabulary from the code,
and they over-represent self-contained functions, so use them to compare configurations, not as an absolute quality score."""
from __future__ import annotations
import random
import re

from ...intel.model import is_test_path
from .dataset import Dataset, Expected, Question

SYSTEM = "You write realistic questions that developers ask about a codebase."


def generate_questions(index, llm, n: int = 30, seed: int = 0, min_lines: int = 4) -> Dataset:
    rng = random.Random(seed)
    pool = [s for s in index.graph.symbols.values()
            if s.kind in ("function", "method", "class") and not is_test_path(s.file) and (s.end - s.start + 1) >= min_lines
            and not s.name.startswith("_") and not s.tags.count("test")]
    rng.shuffle(pool)
    chunks = {c.symbol_id: c for c in index.chunks if c.symbol_id}
    out: list[Question] = []
    rejected = 0
    for s in pool:
        if len(out) >= n:
            break
        c = chunks.get(s.id)
        if c is None:
            continue
        prompt = (f"File: {s.file}\nSymbol: {s.qualname} ({s.kind})\n\n```\n{c.text[:2500]}\n```\n\n"
                  "Write ONE natural-language question a developer might type into a code-search assistant when they need this code. "
                  f"Describe what the code does or where it is, WITHOUT using the identifier `{s.name}` or its exact words. "
                  'Return JSON: {"question": "..."}')
        try:
            q = str(llm.json("generate_question", SYSTEM, prompt, hints={}).get("question", "")).strip()
        except Exception:  # noqa: BLE001
            continue
        words = {w for w in re.split(r"[^a-z0-9]+", s.name.lower().replace("_", " ")) if len(w) > 3}
        leaked = s.name.lower() in q.lower() or (words and all(w in q.lower() for w in words))
        if len(q) < 12 or leaked:
            rejected += 1
            continue
        out.append(Question(f"syn-{len(out) + 1:03d}", q, [Expected(s.file, s.qualname)], ["synthetic", s.kind]))
    return Dataset("synthetic", out, {"generated_by": getattr(llm, "name", "llm"), "seed": seed, "rejected_for_leaking_the_name": rejected})
