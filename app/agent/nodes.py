from __future__ import annotations
from .. import patching, sandbox
from ..config import Settings
from ..llm import LLM
from .state import AgentState, log
from .tools import RepoTools

END = "__end__"
SYSTEM = ("You are a senior software engineer analysing a code repository. "
          "Only make claims the provided code supports. Prefer minimal, targeted fixes.")


def format_context(chunks: list[dict], max_chars: int = 3500) -> str:
    parts = []
    for c in chunks:
        route = f" route={c['route']}" if c.get("route") else ""
        parts.append(f"### {c['file']}:{c['start']}-{c['end']} ({c['qualname']}){route} [{c['via']}]\n```\n{c['text'][:max_chars]}\n```")
    return "\n\n".join(parts)


class AgentRuntime:
    """Graph nodes + routing. Each node takes the state and returns a partial state update.
    The same nodes drive either LangGraph (if installed) or the built-in runner."""

    def __init__(self, llm: LLM, tools: RepoTools, settings: Settings) -> None:
        self.llm, self.tools, self.s = llm, tools, settings

    # ---- nodes -------------------------------------------------------------------------------
    def analyze_query(self, st: AgentState) -> dict:
        q = st["question"]
        prompt = (f"Repository files:\n{self.tools.list_tree(60)}\n\nUser question:\n{q}\n\n"
                  'Return JSON: {"intent": "debug" or "explain", "queries": [up to 4 short code-search queries: '
                  "symbol names, error strings, or concepts]}")
        res = self.llm.json("analyze_query", SYSTEM, prompt, hints={"question": q})
        queries = [x for x in res.get("queries", []) if isinstance(x, str) and x.strip()][:5]
        if q not in queries:
            queries.insert(0, q)
        intent = "debug" if res.get("intent") == "debug" else "explain"
        return {"intent": intent, "queries": queries,
                "steps": log(st, "analyze_query", f"intent={intent}; queries={queries}")}

    def retrieve(self, st: AgentState) -> dict:
        ctx = list(st["context"])
        seen = {c["id"] for c in ctx}
        found = []
        for qry in st["queries"]:
            for h in self.tools.search_code(qry, k=5):
                if h["id"] not in seen:
                    seen.add(h["id"]); found.append(h)
        for h in found[:3]:  # call-graph expansion of the best hits
            for r in self.tools.related(h["id"]):
                if r["id"] not in seen:
                    seen.add(r["id"]); found.append(r)
        ctx = (ctx + found)[: self.s.max_context_chunks]
        msg = "retrieved " + ", ".join(f"{c['file']}::{c['qualname']}" for c in found[:8]) if found else "no new chunks"
        return {"context": ctx, "queries": [], "retrieval_rounds": st["retrieval_rounds"] + 1,
                "steps": log(st, "retrieve", msg, count=len(found))}

    def analyze(self, st: AgentState) -> dict:
        prompt = (f"Question:\n{st['question']}\n\nRetrieved code:\n{format_context(st['context'])}\n\n"
                  'Return JSON: {"need_more": true only if essential code is missing, "follow_up_queries": [..], '
                  '"answer": "explanation grounded in the code", "root_cause": "if this is a bug", '
                  '"affected_file": "path", "affected_function": "name"}')
        res = self.llm.json("analyze", SYSTEM, prompt, hints={"files": list(dict.fromkeys(c["file"] for c in st["context"]))})
        follow = [x for x in res.get("follow_up_queries", []) if isinstance(x, str) and x.strip()][:3]
        need = bool(res.get("need_more")) and bool(follow) and st["retrieval_rounds"] < self.s.max_agent_steps
        return {"analysis": res, "need_more": need, "queries": follow if need else [],
                "steps": log(st, "analyze", "needs more context: " + str(follow) if need else
                             f"analysis done: {res.get('affected_file') or 'n/a'}::{res.get('affected_function') or 'n/a'}")}

    def generate_fix(self, st: AgentState) -> dict:
        feedback = ""
        if st["test_after"] and st["test_after"]["status"] in ("failed", "error"):
            feedback = f"\nYour previous patch FAILED the tests:\n{st['test_after']['output'][-1500:]}\nPrevious edit: {st['edit']}\n"
        prompt = (f"Question / error report:\n{st['question']}\n\nAnalysis: {st['analysis']}\n{feedback}\n"
                  f"Retrieved code:\n{format_context(st['context'])}\n\n"
                  'Return JSON with ONE minimal edit: {"file": "path", "search": "exact existing text that occurs '
                  'exactly once in the file (keep indentation)", "replace": "new text", "explanation": "why"}')
        edit = self.llm.json("generate_fix", SYSTEM, prompt, hints={})
        ok, err = patching.validate_edit(self.tools.root, edit)
        attempts = st["attempts"] + 1
        if not ok:
            return {"edit": None, "diff": "", "fix_error": err, "attempts": attempts,
                    "steps": log(st, "generate_fix", f"no valid patch: {err}")}
        diff = patching.make_diff(self.tools.root, edit)
        return {"edit": edit, "diff": diff, "fix_error": "", "attempts": attempts,
                "steps": log(st, "generate_fix", f"patch proposed for {edit['file']} (attempt {attempts})")}

    def verify(self, st: AgentState) -> dict:
        steps = st["steps"]
        before = st["test_before"]
        if before is None:
            work = sandbox.copy_repo(self.tools.root)
            try:
                before = sandbox.run_tests(work, self.s.test_timeout)
            finally:
                sandbox.cleanup(work)
            steps = steps + [{"node": "verify", "message": f"baseline tests: {before['status']} ({before['summary']})"}]
        work = sandbox.copy_repo(self.tools.root)
        try:
            patching.apply_edit(work, st["edit"])
            after = sandbox.run_tests(work, self.s.test_timeout)
        finally:
            sandbox.cleanup(work)
        steps = steps + [{"node": "verify", "message": f"tests after patch: {after['status']} ({after['summary']})"}]
        return {"test_before": before, "test_after": after, "steps": steps}

    def respond(self, st: AgentState) -> dict:
        a, parts = st["analysis"], []
        if a.get("root_cause"):
            parts.append(f"**Root cause**\n{a['root_cause']}")
        if a.get("answer"):
            parts.append(f"**Analysis**\n{a['answer']}")
        if a.get("affected_file"):
            parts.append(f"**Affected:** `{a['affected_file']}`" + (f" → `{a['affected_function']}()`" if a.get("affected_function") else ""))
        status = "answered"
        if st["allow_fix"] and st["intent"] == "debug":
            if st["edit"]:
                parts.append(f"**Suggested fix**\n```diff\n{st['diff']}```")
                ta = st["test_after"]
                if ta is None:
                    status = "fix_unverified"
                elif ta["status"] == "passed":
                    status = "fix_verified"
                    tb = st["test_before"]
                    parts.append(f"**Verification:** before patch: {tb['status']} ({tb['summary']}); after patch: **passed** ({ta['summary']})")
                else:
                    status = "fix_unverified" if ta["status"] == "no_tests" else "fix_failed"
                    parts.append(f"**Verification:** tests after patch: **{ta['status']}** ({ta['summary']})")
            else:
                status = "no_fix"
                parts.append(f"_No patch generated._ {st['fix_error']}".strip())
        return {"answer": "\n\n".join(parts) or "No answer produced.", "status": status,
                "steps": log(st, "respond", f"status={status}")}

    # ---- routing -----------------------------------------------------------------------------
    def route(self, node: str, st: AgentState) -> str:
        if node == "analyze_query":
            return "retrieve"
        if node == "retrieve":
            return "analyze"
        if node == "analyze":
            if st["need_more"]:
                return "retrieve"
            return "generate_fix" if st["allow_fix"] and st["intent"] == "debug" else "respond"
        if node == "generate_fix":
            if not st["edit"]:
                return "respond"
            return "verify" if st["allow_verify"] else "respond"
        if node == "verify":
            if st["test_after"]["status"] in ("failed", "error") and st["attempts"] < self.s.max_fix_attempts:
                return "generate_fix"
            return "respond"
        return END
