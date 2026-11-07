"""The specialist agents. Each is a small class with one job and its own prompt, tools and output schema; the graph in nodes.py
decides which of them run, and in what order, from the plan the Planner makes and from what happens along the way.

  Planner      task understanding + plan (which specialists, which flags)
  Researcher   function-calling loop: the MODEL chooses retrieval tools; results become ranked evidence
  Debugger     root-cause analysis / explanation grounded in the packed context (an 'analyst' for non-bug questions)
  Coder        exact edits, validated against the files before anything is accepted
  Tester       runs the suite in a throw-away copy, before and after
  Reviewer     deterministic checks + model review of a patch, or a code review of files
  Documenter   architecture / documentation, change notes
"""
from __future__ import annotations
import json
from typing import Callable

from .. import verify
from ..quality import test_patterns as tp
from ..llm.types import LLMBudgetExceeded, LLMContextTooLong, LLMError, LLMRequest, Message
from ..patchset import PatchError, PatchSpec, build_patchset
from ..rag.context import extract_citations
from . import prompts, schemas
from .checks import dedupe_findings, ground_findings, static_checks, suppression_findings
from .errors import ErrorReport, from_test_output, parse_error
from .state import AgentState, log
from .trace import Frame, error_signature, parse_frames, resolve_frames

CODE_TASK = {"debug": "generate_fix", "change": "generate_change", "tests": "generate_tests"}
FORCED_INTENT = {"change": "change", "tests": "tests", "review": "review", "architecture": "docs", "pr_analyze": "pr", "pr_review": "pr"}
FLAT_SCHEMA = {"analyze": '{"need_more": true only if essential code is missing, "follow_up_queries": [..up to 3..], "answer": "explanation grounded in the code, with [n] citations", '
                          '"root_cause": "if this is a bug", "affected_file": "path", "affected_function": "name", "confidence": "low|medium|high"}'}
CODE_SCHEMA = ('Return JSON: {"edits": [{"file": "path", "search": "exact existing text occurring exactly once in that file", "replace": "new text"}], '
               '"new_files": [{"path": "new/file.py", "content": "full file text"}], "delete_files": ["only if a file must go"], "explanation": "what changed and why"}. '
               "Use edits for existing files and new_files only for files that do not exist. Delete a file only when the task requires it. "
               "(A unified diff in \"unified_diff\" is also accepted instead of edits.)")


class Base:
    def __init__(self, rt) -> None:
        self.rt, self.llm, self.tools, self.ctx, self.s = rt, rt.llm, rt.tools, rt.ctx, rt.s

    def json(self, task: str, system: str, build: Callable[[int], str], schema, hints: dict | None = None) -> dict:
        """One structured call. On a context-length error the prompt is rebuilt with half the context budget and tried once more."""
        budget = self.s.context_token_budget
        try:
            res = self.llm.json(task, system, build(budget), hints=hints or {}, schema=schema)
        except LLMContextTooLong:
            res = self.llm.json(task, system, build(self.ctx.shrink(budget)), hints=hints or {}, schema=schema)
        return schema.model_validate(res if isinstance(res, dict) else {}).model_dump()   # idempotent: also normalises offline doubles

    def emit_status(self, message: str) -> None:
        emit = getattr(self.tools, "emit", None)
        if emit:
            emit({"type": "status", "message": message})


# ======================================================================================================
class Planner(Base):
    def _read_screenshots(self, st: AgentState, q: str) -> tuple[str, str]:
        """A vision model turns attached screenshots into text (error messages, stack traces, code, UI state) that the rest of the run treats like pasted text."""
        if not getattr(self.llm, "supports_images", False):
            return q, " (screenshots attached, but this model cannot read images)"
        try:
            resp = self.llm.complete(LLMRequest(task="read_screenshot", system=prompts.SCREENSHOT, messages=[Message(
                "user", "Transcribe everything relevant to a software error in the attached screenshot(s).", images=st["images"][:3])]))
        except LLMBudgetExceeded:
            raise
        except LLMError as e:
            return q, f" (could not read the screenshot: {type(e).__name__})"
        text = (resp.text or "").strip()
        if not text or text.startswith("[mock"):
            return q, " (no text could be read from the screenshot)"
        return f"{q}\n\n[Transcribed from the attached screenshot]\n{text[:6000]}".strip(), f" (read {len(text)} characters from {len(st['images'][:3])} screenshot(s))"

    def understand(self, st: AgentState) -> dict:
        q, mode = st["question"], st.get("mode", "chat")
        shot_note = ""
        if st.get("images"):
            q, shot_note = self._read_screenshots(st, q)
        tree = self.tools.index.tree
        report = parse_error(q, tree, lambda f, n: self.tools.read_file(f, n, n))
        if report.function:      # who calls the failing function, and what else is on the stack
            rel = [{"name": c["caller"], "file": c["file"], "relation": f"calls {report.function}()"} for c in self.tools.callers(report.function)[:4]]
            rel += [{"name": f["func"], "file": f["file"], "relation": "on the call stack"} for f in report.frames[:-1] if f["func"]][-3:]
            report.related_functions = rel[:6]
        frames = [Frame(f["file"], f["line"], f["func"]) for f in report.frames]
        sig = error_signature(q) or (f"{report.exception_type}: {report.message}"[:200] if report.exception_type else "")
        entities_hint = {"files": [st["target"]] if st.get("target") else []}

        def build(_budget: int) -> str:
            return (f"Repository: {self.ctx.repo_map(entities_hint)}{self.ctx.history_block(st.get('history', ''))}"
                    f"{report_block(report)}\n\nRequest:\n{q[:4000]}\n\n"
                    'Return JSON: {"intent": "explain|debug|change|tests|review|docs", "summary": "one sentence: what is being asked", '
                    '"queries": [up to 4 short code-search queries: symbol names, error strings, concepts], "symbols": [identifiers named or implied], '
                    '"files": [paths named or implied], "errors": [exact error messages], "follow_up": true if it refers to the previous turn, '
                    '"complexity": "simple|moderate|complex"}')
        degraded = ""
        try:
            if getattr(self.s, "fast_planning", True) and mode == "chat" and not (frames or sig) and not st.get("images"):
                # a plain question: no model call is needed to classify it (saves a round trip; the research step chooses the tools)
                res, degraded = schemas.Understanding().model_dump(), " (fast path: no planning model call)"
                res["intent"] = "explain"
            else:
                res = self.json("understand", prompts.UNDERSTAND, build, schemas.Understanding, hints={"question": q})
        except LLMBudgetExceeded:
            raise
        except LLMError as e:    # planning must never be what kills a run: fall back to plain heuristics
            res, degraded = schemas.Understanding().model_dump(), f" (model unavailable: {type(e).__name__}; used heuristics)"
            res["intent"] = "debug" if (frames or sig) else "explain"
        intent = FORCED_INTENT.get(mode) or res["intent"]
        if mode in ("chat", "debug", "fix", "repair", "issue") and intent not in ("explain", "debug"):
            intent = "debug" if mode in ("debug", "fix", "repair") and intent == "change" else "change" if mode == "issue" and intent == "change" else "explain"
        if mode == "repair":
            intent = "debug"
        files = list(dict.fromkeys(([st["target"]] if st.get("target") else []) + [f.file for f in frames] + res["files"]
                                   + (self.rt.store.last_files(st.get("conversation_id")) if res["follow_up"] else [])))
        symbols = list(dict.fromkeys(([report.function] if report.function else []) + [f.func for f in frames if f.func and f.func != "<module>"] + res["symbols"]))
        errors = list(dict.fromkeys(([sig] if sig else []) + res["errors"]))[:4]
        queries = [x for x in res["queries"] if x.strip()][:5]
        for extra in ([sig] if sig else []) + ([f"{symbols[0]}"] if symbols else []):
            if extra not in queries:
                queries.append(extra)
        if q[:300] not in queries:
            queries.insert(0, q[:300])
        und = {**res, "intent": intent}
        found = f"; error: {report.headline()}" if report.found else ""
        out = {"intent": intent, "understanding": und, "entities": {"symbols": symbols[:8], "files": files[:8], "errors": errors},
               "frames": report.frames, "error_report": report.to_dict(), "queries": queries[:6],
               "steps": log(st, "understand", f"intent={intent}, complexity={res['complexity']}; queries={queries[:4]}{found}{shot_note}" + degraded)}
        if q != st["question"]:
            out["question"] = q
        return out

    def plan(self, st: AgentState) -> dict:
        intent, und = st["intent"], st.get("understanding", {})

        def build(_b: int) -> str:
            return (f"Intent: {intent}. Summary: {und.get('summary', '')}. Complexity: {und.get('complexity', 'moderate')}.\n"
                    f"Code changes allowed: {st['allow_fix']}. Running tests allowed: {st['allow_verify']}.\nRequest:\n{st['question'][:1500]}\n\n"
                    'Return JSON: {"steps": [{"agent": "researcher|debugger|coder|tester|reviewer|documenter", "goal": "..."}], '
                    '"needs_patch": bool, "needs_review": bool, "needs_regression_test": bool, "needs_docs": bool, "rationale": "one sentence"}')
        degraded = ""
        try:
            if getattr(self.s, "fast_planning", True) and intent == "explain":
                raw, degraded = schemas.Plan().model_dump(), " (fast path: default plan)"
            else:
                raw = self.json("plan", prompts.PLAN, build, schemas.Plan)
        except LLMBudgetExceeded:
            raise
        except LLMError as e:
            raw, degraded = schemas.Plan().model_dump(), f" (model unavailable: {type(e).__name__}; default plan)"
        has_tests = any(verify.is_test_file(f) for f in self.tools.index.tree)
        plan = normalize_plan(raw, intent, st["allow_fix"], st["allow_verify"], und.get("complexity", "moderate"), has_tests)
        return {"plan": plan, "steps": log(st, "plan", " → ".join(s["agent"] for s in plan["steps"])
                                           + (f" — {plan['rationale']}" if plan["rationale"] else "") + degraded)}


def report_block(rep: ErrorReport) -> str:
    """The structured error facts as prompt text ('' when the request contains no error)."""
    if not rep.found and not rep.http_status:
        return ""
    lines = ["\n\nParsed error report (extracted by the tool, verify against the code):", f"- exception: {rep.exception_type or 'unknown'}" + (f": {rep.message}" if rep.message else ""),
             f"- kind: {rep.category or 'unclassified'}" + (f"; language: {rep.language}" if rep.language else "") + (f"; HTTP status: {rep.http_status}" if rep.http_status else "")]
    if rep.file:
        lines.append(f"- failing location: {rep.file}:{rep.line}" + (f" in {rep.function}()" if rep.function else "") + (f"\n- failing line: {rep.code_line}" if rep.code_line else ""))
    if rep.variables:
        lines.append("- variables involved: " + "; ".join(f"{v['name']} ({v['evidence']})" for v in rep.variables))
    if rep.frames:
        lines.append("- call stack in this repository (outermost first): " + " → ".join(f"{f['file']}:{f['line']}" + (f" {f['func']}()" if f["func"] else "") for f in rep.frames[-6:]))
    if rep.chained:
        lines.append("- related exceptions in the report: " + " | ".join(rep.chained))
    if rep.related_functions:
        lines.append("- related functions: " + "; ".join(f"{r['name']} ({r['relation']})" for r in rep.related_functions))
    return "\n".join(lines)


def normalize_plan(raw: dict, intent: str, allow_fix: bool, allow_verify: bool, complexity: str = "moderate", has_tests: bool = False) -> dict:
    """The planner proposes; this enforces what is allowed and fills what it left out. The result drives the graph's routing."""
    if intent == "pr":
        return {"steps": [{"agent": "researcher", "goal": ""}, {"agent": "reviewer", "goal": ""}], "needs_patch": False, "needs_tester": False, "needs_review": True,
                "needs_regression_test": False, "needs_docs": False, "rationale": raw.get("rationale", "")}
    patch_intent = intent in ("debug", "change", "tests")
    needs_patch = allow_fix and patch_intent and (raw.get("needs_patch") is not False or intent in ("change", "tests"))
    needs_tester = needs_patch and allow_verify
    needs_review = intent == "review" or (needs_patch and (raw.get("needs_review") if raw.get("needs_review") is not None else complexity != "simple"))
    if raw.get("needs_regression_test") is None:      # a bug fix is only demonstrably fixed if a test fails before it and passes after
        regression = needs_patch and intent == "debug" and allow_verify and has_tests
    else:
        regression = needs_patch and intent != "tests" and bool(raw["needs_regression_test"])
    needs_docs = bool(raw.get("needs_docs")) and needs_patch and intent != "docs"
    goals = {s["agent"]: s.get("goal", "") for s in raw.get("steps", [])}
    order = ["researcher"]
    if intent in ("debug", "explain", "change"):
        order.append("debugger")
    if needs_patch:
        order.append("coder")
    if needs_tester:
        order.append("tester")
    if needs_review:
        order.append("reviewer")
    if intent == "docs" or needs_docs:
        order.append("documenter")
    return {"steps": [{"agent": a, "goal": goals.get(a, "")} for a in order], "needs_patch": needs_patch, "needs_tester": needs_tester,
            "needs_review": bool(needs_review), "needs_regression_test": bool(regression), "needs_docs": needs_docs, "rationale": raw.get("rationale", "")}


# ======================================================================================================
class Researcher(Base):
    def reproduce(self, st: AgentState) -> dict:
        """Run the tests before changing anything: a failing test is the best evidence there is, and the baseline is reused for verification."""
        self.emit_status("Reproducing: running the tests on the original code…")
        run = self.tools.run_tests()
        chunks: list[dict] = []
        out: dict = {"test_before": run}
        if run["status"] == "failed" and run.get("output"):
            for f in resolve_frames(parse_frames(run["output"]), self.tools.index.tree)[-4:]:
                c = self.tools.chunk_at(f.file, f.line)
                if c:
                    chunks.append(c)
            for t in run.get("failed_tests", [])[:2]:
                name = t["id"].split("::")[-1].split("[")[0]
                chunks += self.tools.find_symbol(name)[:1]
            if not st["error_report"].get("exception_type") and not st["error_report"].get("frames"):
                rep = from_test_output(run["output"], self.tools.index.tree, lambda f, n: self.tools.read_file(f, n, n))
                if rep.found:
                    out["error_report"] = rep.to_dict()
                    out["frames"] = rep.frames
            fails = "; ".join(f"{t['id']}" + (f" ({t['message']})" if t["message"] else "") for t in run.get("failed_tests", [])[:4])
            out["repro_note"] = f"Test run on the original code: {run['summary']}. Failing: {fails or 'see output'}\n{run['output'][-1200:]}"
        elif run["status"] == "passed":
            out["repro_note"] = f"Test run on the original code: {run['summary']}. The existing tests do NOT reproduce the problem."
        out["_chunks"] = chunks
        return out

    def run(self, st: AgentState) -> dict:
        evidence = list(st.get("evidence", []))
        seen = {c["id"] for c in evidence}
        before = len(evidence)
        used = st.get("tool_calls_used", 0)
        names: list[str] = []
        extra: dict = {}

        def add(chunks: list[dict]) -> int:
            n = 0
            for c in chunks:
                if c["id"] not in seen:
                    seen.add(c["id"]); evidence.append(c); n += 1
            return n

        # 1. free, exact leads: the failing frames, the symbols the user named, and (for bugs) what the tests say
        entities = st["entities"]
        if st["retrieval_rounds"] == 0:
            for f in st.get("frames", [])[-4:]:
                c = self.tools.chunk_at(f["file"], f["line"])
                if c:
                    add([c])
            for sym in entities["symbols"][:3]:
                add(self.tools.find_symbol(sym)[:2])
            if st["intent"] == "pr" and st.get("pr"):
                changed = {f["path"]: set(st["pr"]["valid_lines"].get(f["path"], [])) for f in st["pr"]["files"]}
                for c in self.tools.index.chunks:
                    lines = changed.get(c.file)
                    if lines and any(c.start <= n <= c.end for n in lines) and len(evidence) - before < 14:
                        from .tools import chunk_dict
                        d = chunk_dict(c, via="diff")
                        add([d])
            if st["intent"] == "debug" and st["allow_verify"] and st["test_before"] is None and self.rt.registry.max_test_runs > 0:
                rep = self.reproduce(st)
                add(rep.pop("_chunks", []))
                extra.update(rep)
                if rep.get("error_report"):
                    entities = {**entities, "symbols": list(dict.fromkeys(entities["symbols"] + [f["func"] for f in rep["frames"] if f["func"]]))[:8]}
        pending = list(st.get("queries", []))

        # 2. the model picks tools
        specs = self.rt.registry.specs("researcher")
        known = ", ".join(f"{c['file']}::{c['qualname']}" for c in evidence[:10]) or "nothing yet"
        task = (f"Task ({st['intent']}): {st['question'][:2500]}\n" + (f"Summary: {st['understanding'].get('summary', '')}\n" if st.get("understanding") else "")
                + f"Repository: {self.ctx.repo_map(entities)}{self.ctx.history_block(st.get('history', ''))}"
                + (report_block(ErrorReport(**{k: v for k, v in (extra.get('error_report') or st.get('error_report') or {}).items() if k in ErrorReport.__dataclass_fields__})) if (extra.get("error_report") or st.get("error_report")) else "")
                + (f"\n{extra.get('repro_note') or st.get('repro_note', '')}\n" if (extra.get("repro_note") or st.get("repro_note")) else "") + "\n"
                + f"Already found: {known}.\n"
                + (f"Missing context to look for: {pending}\n" if pending and st["retrieval_rounds"] else "")
                + (f"Suggested starting searches: {pending}\n" if pending and not st["retrieval_rounds"] else "")
                + f"Tools available: {', '.join(self.rt.registry.names('researcher'))}. You may make up to {self.s.max_tool_calls} tool calls.")
        msgs = [Message("user", task)]
        tried: set[str] = set()
        round_calls = 0
        note = ""
        try:
            for _ in range(self.s.max_tool_iterations):
                resp = self.llm.complete(LLMRequest(task="research", system=prompts.RESEARCH, messages=msgs, tools=specs,
                                                    hints={"question": st["question"], "queries": pending}))
                msgs.append(Message("assistant", resp.text, tool_calls=resp.tool_calls, raw=resp.raw))
                if not resp.tool_calls:
                    note = resp.text.strip()[:200]
                    break
                for call in resp.tool_calls[:4]:
                    key = f"{call.name}:{json.dumps(call.args, sort_keys=True)}"
                    if key in tried:
                        text = "You already made this exact call. Use a different query or stop."
                    elif round_calls >= self.s.max_tool_calls:
                        text = "Tool budget for this round is used up. Reply now without a tool call."
                    else:
                        tried.add(key); round_calls += 1; names.append(call.name)
                        res = self.rt.registry.execute(call.name, call.args)
                        add(res.chunks)
                        text = res.text
                    msgs.append(Message("tool", text, tool_call_id=call.id, name=call.name))
                if round_calls >= self.s.max_tool_calls:
                    break
        except LLMBudgetExceeded:
            raise
        except LLMError as e:
            note = f"tool selection unavailable ({type(e).__name__})"

        # 3. safety net: if the model found nothing (no tool use, or none supported), search the planned queries directly
        if len(evidence) == before:
            for q in pending[:5]:
                add(self.tools.search_code(q, k=5)); names.append("search_code"); round_calls += 1
        # 4. call-graph neighbours of the best search hits, unless the model already walked the graph itself
        if not {"get_callers", "get_callees", "callers", "callees"} & set(names):
            for h in [c for c in evidence if c.get("via") == "search" and isinstance(c["id"], int)][:2]:
                add(self.tools.related(h["id"])[:4])

        built = self.ctx.build(evidence, entities, st["intent"])
        uniq = list(dict.fromkeys(names))
        repro = f"; reproduction: tests {extra['test_before']['status']} ({extra['test_before']['summary']})" if extra.get("test_before") else ""
        msg = (f"{round_calls} tool call(s) [{', '.join(uniq) or 'none'}]; {len(evidence) - before} new snippet(s); "
               f"context {built.report['kept']} snippets / {built.report['tokens']} of {built.report['budget']} tokens{repro}" + (f" — {note}" if note else ""))
        out = {"evidence": evidence, "context": built.chunks, "context_report": built.report, "queries": [], "need_more": False,
               "retrieval_rounds": st["retrieval_rounds"] + 1, "tool_calls_used": used + round_calls + (1 if extra.get("test_before") else 0),
               "steps": log(st, "research", msg, count=len(evidence) - before)}
        out.update({k: v for k, v in extra.items() if k in ("test_before", "repro_note", "error_report", "frames")})
        if out.get("frames") and "entities" not in out and entities is not st["entities"]:
            out["entities"] = entities
        return out


def _frames(st: AgentState):
    return [Frame(f["file"], f["line"], f.get("func", "")) for f in st.get("frames", [])]


# ======================================================================================================
class Debugger(Base):
    """Root-cause analysis for bugs; plain grounded explanation for questions."""

    def run(self, st: AgentState) -> dict:
        role = "debugger" if st["intent"] == "debug" else "analyst"
        files = list(dict.fromkeys(c["file"] for c in st["context"]))
        rep = ErrorReport(**{k: v for k, v in (st.get("error_report") or {}).items() if k in ErrorReport.__dataclass_fields__})

        def build(budget: int) -> str:
            built = self.ctx.build(st["evidence"], st["entities"], st["intent"], budget=budget) if budget < self.s.context_token_budget else None
            ctx_text = (built.sections() if built else f"Retrieved code:\n{_render(st)}{self.ctx.relations(st['context'])}\n\n{_rules()}")
            return (f"Question / error report:\n{st['question'][:4000]}{report_block(rep)}{self.ctx.history_block(st.get('history', ''))}"
                    + (f"\n\n{st['repro_note']}" if st.get("repro_note") else "") + f"\n\n{ctx_text}\n\nReturn JSON: {FLAT_SCHEMA['analyze']}")
        res = self.json("analyze", prompts.ANALYZE.format(role=role), build, schemas.Analysis, hints={"files": files})
        need = bool(res["need_more"]) and bool(res["follow_up_queries"]) and st["retrieval_rounds"] < self.s.max_agent_steps
        msg = ("needs more context: " + str(res["follow_up_queries"]) if need else
               f"analysis done ({role}): {res['affected_file'] or 'n/a'}::{res['affected_function'] or 'n/a'}")
        return {"analysis": res, "need_more": need, "queries": res["follow_up_queries"] if need else [], "steps": log(st, "analyze", msg)}


def _render(st: AgentState) -> str:
    from ..rag.context import render_blocks
    return render_blocks(st["context"], 3500)


def _rules() -> str:
    from ..rag.context import CITATION_RULES
    return CITATION_RULES


# ======================================================================================================
class Coder(Base):
    """Writes the change. With a function-calling model it works in a loop: generate_patch (validated against the real files) →
    apply_patch (checked in a sandbox copy) → fix what they report. Without one it asks for one JSON patch. Either way the result is
    rebuilt and validated by the patch engine before it is accepted, and nothing is written to the repository."""

    def _tool_loop(self, head: str, build_ctx: Callable[[int], str]) -> tuple[dict | None, str]:
        reg = self.rt.registry
        reg.pending = None
        msgs = [Message("user", f"{head}\n\n{build_ctx(self.s.context_token_budget)}\n\nTools available: {', '.join(reg.names('coder'))}.")]
        specs = reg.specs("coder")
        text = ""
        for i in range(self.s.max_tool_iterations + 3):
            resp = self.llm.complete(LLMRequest(task="code", system=prompts.CODE, messages=msgs, tools=specs, hints={}))
            msgs.append(Message("assistant", resp.text, tool_calls=resp.tool_calls, raw=resp.raw))
            if not resp.tool_calls:
                text = resp.text.strip()
                break
            for call in resp.tool_calls[:4]:
                res = reg.execute(call.name, call.args)
                msgs.append(Message("tool", res.text, tool_call_id=call.id, name=call.name))
        pend = reg.pending
        return (pend["spec"] if pend else None), (text or (pend or {}).get("explanation", ""))

    def run(self, st: AgentState) -> dict:
        intent = st["intent"]
        task = CODE_TASK.get(intent, "generate_change")
        attempts = st["attempts"] + 1
        analysis = st.get("analysis") or {}
        if intent == "tests" and st.get("target"):
            analysis = {"affected_file": st["target"]}
        files = [e["file"] for e in st.get("edits", [])] + st["entities"]["files"][:2]
        feedback = self._feedback(st)
        allow_impl = intent == "tests" and (st.get("reflection") or {}).get("culprit") == "implementation" and (st.get("verification") or {}).get("status") == "not_resolved"
        patterns_update: dict = {}
        head = {"debug": f"Fix this problem with the smallest correct change.\n\nProblem report:\n{st['question'][:3000]}\n\nAnalysis: {_brief(analysis)}",
                "change": f"Implement this change across the codebase. Touch as few files as needed and follow the existing style.\n\nRequest:\n{st['question'][:3000]}",
                "tests": self._tests_head(st)}[intent if intent in CODE_TASK else "change"]
        if st["plan"].get("needs_regression_test"):
            head += ("\nAlso add ONE regression test for this change as a new file under tests/ (new_files). It must FAIL on the current code (it reproduces the problem) "
                     "and PASS after your fix; keep it small and self-contained.")

        def build(budget: int) -> str:
            built = self.ctx.build(st["evidence"], st["entities"], intent, budget=budget)
            target = self.ctx.target_code(analysis, files if intent != "debug" else None)
            return ((f"Code to modify (exact, current text):\n{target}\n\n" if target else "") + f"{built.sections()}\n{feedback}")

        if intent == "tests":
            patterns_update = {"test_patterns": {k: getattr(self, "_patterns", {}).get(k) for k in ("framework", "language", "test_files", "layout", "suggested_path", "assertions", "mocking", "fixtures", "parametrized", "sample_path")}}
        spec_dict, explanation, via_tools = None, "", False
        if getattr(self.llm, "supports_tools", False):
            try:
                spec_dict, explanation = self._tool_loop(head, build)
                via_tools = spec_dict is not None
            except LLMBudgetExceeded:
                raise
            except LLMContextTooLong:
                spec_dict = None
        if spec_dict is None:
            res = self.json(task, prompts.CODE, lambda b: f"{head}\n\n{build(b)}\n{CODE_SCHEMA}", schemas.CodeChange)
            spec_dict = {k: res[k] for k in ("edits", "new_files", "delete_files", "rewrites", "unified_diff")}
            spec_dict["rewrites"] = [dict(r) for r in spec_dict["rewrites"]]
            explanation = res["explanation"]
        spec = PatchSpec.from_dict(spec_dict)
        proposed = not spec.empty()
        err, ps = "", None
        if proposed:
            try:
                ps = build_patchset(self.tools.root, spec, allow_noop=True)
            except PatchError as e:
                err = str(e)
        else:
            err = "no changes proposed"
        impl_change = False
        if ps is not None and intent == "tests":
            non_test = [c.path for c in ps.changes if not verify.is_test_file(c.path)]
            new_tests = [c.path for c in ps.changes if c.op == "create" and verify.is_test_file(c.path)]
            if not new_tests and not any(verify.is_test_file(c.path) for c in ps.changes):
                err, ps = "a test file is required: add one with new_files, following the repository's test layout", None
            elif non_test and not allow_impl:
                err, ps = (f"generated tests must live in test files; do not change implementation code ({', '.join(non_test[:3])}). "
                           "If a test reveals a bug, say so in `explanation` instead."), None
            elif non_test:
                impl_change = True
        if ps is None:
            msg = f"attempt {attempts} rejected: {err}" if proposed else f"attempt {attempts}: the model proposed no change"
            return {"fix_error": err, "proposed": proposed, "attempts": attempts, "explanation": explanation or st.get("explanation", ""),
                    "steps": log(st, "generate", msg)}
        single = spec.edits[0] if len(spec.edits) == 1 and not (spec.new_files or spec.delete_files or spec.rewrites or spec.unified_diff) else None
        s = ps.stats()
        fz = [n for c in ps.changes for n in c.notes]
        summary = (f"attempt {attempts}: {s['files']} file(s) (+{s['additions']}/-{s['deletions']}): {', '.join(ps.paths)}"
                   + (f"; {s['created']} new" if s["created"] else "") + (f"; {s['deleted']} deleted" if s["deleted"] else "")
                   + ("; written through function calling" if via_tools else "") + (f"; note: {fz[0]}" if fz else ""))
        return {"edits": spec.edits, "new_files": spec.new_files, "delete_files": spec.delete_files, "spec": spec.to_dict(), "edit": single,
                "explanation": explanation, "diff": ps.diff, "patch_files": [c.summary() for c in ps.changes],
                "final_files": {c.path: (c.new or "")[:200_000] for c in ps.changes if c.op != "delete"}, "fix_error": "", "proposed": True, "attempts": attempts,
                "test_after": None, "review": None, "verification": None, "regression": None, "impl_change": impl_change, "coverage_delta": None,
                "steps": log(st, "generate", summary + ("; includes an IMPLEMENTATION change because a test exposed a bug" if impl_change else "")),
                **patterns_update}

    def _tests_head(self, st: AgentState) -> str:
        target = st.get("target") or ""
        pat = tp.analyze(self.tools.root, self.tools.index.tree, target)
        self._patterns = pat
        fw = pat["framework"]
        goal = (f"Write {fw} tests for `{target}`" if target else f"Write {fw} tests for: {st['question'][:300]}")
        return (f"{goal}.\nCover normal behaviour, edge cases (empty / None / boundary values) and error handling with unit tests; add one integration-style test when the code "
                "touches several components, doing external I/O (network, files, clock) through the same mocking approach the repository already uses. "
                "Tests must be deterministic and independent. Add NEW test file(s) with new_files and do not change implementation code. "
                "If you believe the code under test has a bug, write the test for the CORRECT behaviour and say so in `explanation`.\n\n" + tp.render(pat))

    @staticmethod
    def _feedback(st: AgentState) -> str:
        parts = []
        if st.get("fix_error") and st.get("proposed"):
            parts.append(f"Your previous answer was invalid: {st['fix_error']}")
        v, ta = st.get("verification"), st.get("test_after")
        if v and v["status"] == "not_resolved":
            parts.append(f"Your previous patch did not solve it: {v['summary']}.")
            if ta and ta["status"] in ("failed", "error"):
                parts.append(f"Test output:\n{ta['output'][-1500:]}")
            blocking = [i for i in st.get("lint_new", []) if i.get("blocking")]
            if blocking:
                parts.append("It also introduced blocking lint errors:\n" + "\n".join(f"- {i['file']}:{i['line']} {i['code']} {i['message']}" for i in blocking[:5]))
            parts.append(f"Previous patch:\n{(st.get('diff') or '')[:1800]}")
        elif v and v["status"] == "unverified" and st["plan"].get("needs_regression_test") and (v.get("reasons") or st.get("regression")):
            parts.append("The previous patch could not be shown to fix the problem: " + (v["reasons"][0] if v.get("reasons") else v["summary"]))
        rv = st.get("review")
        if rv and not rv.get("approved"):
            parts.append(f"A reviewer rejected your previous patch: {rv.get('feedback') or rv.get('summary')}")
        rf = st.get("reflection") or {}
        if rf.get("reason") and v and v["status"] == "not_resolved":
            parts.append(f"Diagnosis of the failure: {rf['reason']}")
            if st["intent"] == "tests" and rf.get("culprit") == "implementation":
                parts.append("The failing test is believed to be CORRECT and to have exposed a real bug. Keep the test; make the smallest fix to the implementation (edits to source "
                             "files are allowed now) and explain the bug in `explanation`.")
            elif st["intent"] == "tests":
                parts.append("The implementation is believed to be correct: fix the TEST (wrong expectation, import, setup or mocking); do not change implementation code.")
        return ("\n" + "\n".join(parts) + "\n") if parts else ""


def _brief(a: dict) -> str:
    return json.dumps({k: a.get(k) for k in ("root_cause", "affected_file", "affected_function", "answer") if a.get(k)})[:1500]


# ======================================================================================================
class Tester(Base):
    def run(self, st: AgentState) -> dict:
        """Verify the patch in throw-away copies: baseline, reproduction by the regression test, then tests + lint with the patch applied."""
        baseline = {"tests": st["test_before"]} if st["test_before"] is not None else None
        res = verify.verify_patch(self.tools.root, st["spec"], timeout=self.tools.test_timeout, baseline=baseline, intent=st["intent"], progress=self.emit_status,
                                  coverage=st["intent"] == "tests", coverage_files=[st["target"]] if st["intent"] == "tests" and st.get("target") else None)
        steps = st["steps"]
        if baseline is None:
            steps = steps + [{"node": "verify", "message": f"baseline tests: {res['test_before']['status']} ({res['test_before']['summary']})"}]
        rg = res["regression"]
        if rg:
            steps = steps + [{"node": "verify", "message": f"regression test {', '.join(rg['tests'])}: "
                              + ("fails on the original code (reproduces the problem)" if rg["failed_before"] else "does NOT fail on the original code")
                              + ("; passes with the fix" if rg["passed_after"] else "; still fails with the fix")}]
        steps = steps + [{"node": "verify", "message": f"tests after patch: {res['test_after']['status']} ({res['test_after']['summary']})"}]
        steps = steps + [{"node": "verify", "message": f"lint ({res['lint_after']['tool']}): {len(res['lint_new'])} new finding(s), {sum(1 for i in res['lint_new'] if i['blocking'])} blocking"}]
        v = res["verification"]
        steps = steps + [{"node": "verify", "message": f"verdict: {v['status']} — {v['summary']}"}]
        cd = res.get("coverage")
        if cd:
            steps = steps + [{"node": "verify", "message": f"coverage {cd['before']}% → {cd['after']}%" + "".join(f"; {f['path']} {f['before']}% → {f['after']}%" for f in cd["files"][:2])}]
        return {"test_before": res["test_before"], "test_after": res["test_after"], "lint_before": res["lint_before"], "lint_after": res["lint_after"],
                "lint_new": res["lint_new"], "regression": rg, "verification": v, "coverage_delta": cd, "steps": steps}

    def reflect(self, st: AgentState) -> dict:
        ta, v = st["test_after"], st["verification"] or {}
        blocking = [i for i in st.get("lint_new", []) if i.get("blocking")]

        def build(_b: int) -> str:
            return (f"Problem: {st['question'][:1500]}\nAnalysis: {_brief(st.get('analysis') or {})}\n\nYour patch:\n```diff\n{st['diff'][:3000]}```\n"
                    f"It did NOT solve the problem: {v.get('summary', 'tests failed')}.\nTest run after the patch ({ta['status']}): {ta['output'][-1800:]}\n"
                    + ("New blocking lint errors:\n" + "\n".join(f"- {i['file']}:{i['line']} {i['code']} {i['message']}" for i in blocking[:5]) + "\n" if blocking else "")
                    + ("\nThese are GENERATED tests that failed. Decide whether the TEST is wrong (bad expectation, import, setup, mocking) or the IMPLEMENTATION has a real bug the test "
                       "caught; set \"culprit\" to \"test\" or \"implementation\".\n" if st["intent"] == "tests" else "")
                    + '\nReturn JSON: {"action": "retry_code|research_more|stop", "culprit": "test|implementation", "reason": "what went wrong and what to change", "queries": [searches if research_more]}')
        degraded = ""
        try:
            res = self.json("reflect", prompts.REFLECT, build, schemas.Reflection)
        except LLMBudgetExceeded:
            raise
        except LLMError as e:
            res, degraded = schemas.Reflection().model_dump(), f" (model unavailable: {type(e).__name__})"
        if res["action"] == "research_more" and (not res["queries"] or st["retrieval_rounds"] >= self.s.max_agent_steps):
            res["action"] = "retry_code"
        out = {"reflection": res, "steps": log(st, "reflect", f"{res['action']}: {res['reason'][:160]}" + (f" (culprit: {res['culprit']})" if st["intent"] == "tests" else "") + degraded)}
        if res["action"] == "research_more":
            out["queries"] = res["queries"]
        return out


# ======================================================================================================
class PRReviewer(Base):
    """Pull requests: analysis (what changed, how risky, what it touches) and review drafts (inline comments anchored to real diff lines).
    Static analyzers run on the PR's head files in the sandbox and only findings on ADDED lines count. Nothing is ever posted from here."""

    def _static(self, st: AgentState) -> tuple[list[dict], str]:
        pr = st["pr"]
        if not pr.get("head_fetched"):
            return [], "static analysis skipped: the PR head could not be fetched into the local clone"
        from ..pr_context import head_files
        from ..quality import analyzers
        import shutil, tempfile
        from pathlib import Path
        paths = [f["path"] for f in pr["files"] if f["status"] != "removed"]
        files = head_files(self.tools.root, pr["pr"]["number"], paths)
        if not files:
            return [], "static analysis skipped: no changed files could be read at the PR head"
        work = Path(tempfile.mkdtemp(prefix="agent-pr-"))
        try:
            for p, text in files.items():
                (work / p).parent.mkdir(parents=True, exist_ok=True)
                (work / p).write_text(text)
            for cfg in ("pyproject.toml", "ruff.toml", ".ruff.toml", "setup.cfg", ".flake8", ".eslintrc.json", ".eslintrc.js", "eslint.config.js", "package.json"):
                if (self.tools.root / cfg).is_file() and not (work / cfg).exists():
                    shutil.copy(self.tools.root / cfg, work / cfg)
            found: list[dict] = []
            ran = []
            for name in [n for n in ("ruff", "bandit", "semgrep", "eslint") if n in analyzers.ANALYZERS and analyzers.ANALYZERS[n].applies(work)]:
                res = analyzers.run(work, name)
                if res.status in ("ok", "issues"):
                    ran.append(name)
                for f in res.findings:
                    if f.line in set(pr["added_lines"].get(f.file, [])):
                        found.append(f.to_dict())
            return found[:40], f"static analysis ({', '.join(ran) or 'no tool available'}): {len(found)} finding(s) on lines this PR adds"
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def run(self, st: AgentState) -> dict:
        pr = st["pr"]
        if not pr:
            return {"pr_report": {}, "steps": log(st, "review", "no pull request context was provided")}
        from ..pr_context import render_pr
        review = st["mode"] == "pr_review"
        static, static_note = self._static(st)
        paths = [f["path"] for f in pr["files"]]
        impact_lines = []
        for p in paths[:8]:
            try:
                im = self.tools.impact(p)
                impact_lines.append(f"- {p}: {len(im['dependents'])} dependent file(s)" + (f", tests: {', '.join(im['tests'][:3])}" if im["tests"] else ", no tests depend on it"))
            except (ValueError, KeyError):
                pass
        tests_touched = [p for p in paths if verify.is_test_file(p)]
        pr_text = render_pr(pr)
        ctx = self.ctx.build(st["evidence"], {"files": paths}, "review", budget=min(self.s.context_token_budget, 3500))
        facts = (f"{static_note}\n" + ("\n".join(f"- {f['file']}:{f['line']} [{f['tool']} {f['code']}, {f['severity']}] {f['message']}" for f in static[:20]) if static else "") +
                 "\nImpact (from the call/import graph of the local checkout, which approximates the base branch):\n" + ("\n".join(impact_lines) or "n/a") +
                 f"\nTest files changed in this PR: {', '.join(tests_touched) or 'none'}")

        def build(_b: int) -> str:
            base = f"{pr_text}\n\n{facts}\n\nRelated code in the repository:\n{ctx.code}{ctx.relations}\n\n"
            if review:
                return (base + "Write a code review of this pull request. Only comment on lines that appear in the diff above. Be specific and actionable; skip style nits unless they matter. "
                        "Do not repeat the existing discussion. Praise nothing; no issues is a valid outcome. "
                        'Return JSON: {"verdict": "approve|comment|request_changes", "summary": "overall assessment in 2-4 sentences", '
                        '"comments": [{"path": "file", "line": <new-file line in the diff>, "severity": "high|medium|low|nit", "body": "what is wrong and how to fix it"}]}')
            return (base + "Analyse this pull request for a reviewer who has not read it. "
                    'Return JSON: {"summary": "what it does and why, 2-4 sentences", "change_type": "feature|bugfix|refactor|docs|chore|dependencies|tests|mixed", "risk": "low|medium|high", '
                    '"risk_reasons": [..], "key_changes": [{"file": "path", "what": "..."}], "impact": ["parts of the system affected"], "test_assessment": "are the changes tested? what is missing?", '
                    '"concerns": [{"file": "path", "line": 0, "severity": "high|medium|low", "message": ".."}], "questions": ["to ask the author"]}')
        degraded = ""
        try:
            res = self.json("pr_review" if review else "pr_analyze", prompts.PR_REVIEW if review else prompts.PR_ANALYZE, build, schemas.ReviewDraft if review else schemas.PRAnalysis,
                            hints={"question": st["question"]})
        except LLMBudgetExceeded:
            raise
        except LLMError as e:
            res, degraded = (schemas.ReviewDraft() if review else schemas.PRAnalysis()).model_dump(), f" (model unavailable: {type(e).__name__}; automatic findings only)"
        report: dict
        if review:
            valid = {p: set(v) for p, v in pr["valid_lines"].items()}
            anchored, loose, seen = [], [], set()
            existing = {(f["path"], f["line"]) for f in pr["feedback"] if f.get("path")}
            for c in res["comments"]:
                if not c["body"].strip():
                    continue
                key = (c["path"], c["line"])
                if c["line"] in valid.get(c["path"], set()) and key not in seen and key not in existing:
                    seen.add(key); anchored.append({**c, "source": "ai"})
                else:
                    loose.append(c)
            for f in static:
                key = (f["file"], f["line"])
                if key not in seen and f["severity"] in ("high", "medium") and f["line"] in valid.get(f["file"], set()):
                    seen.add(key)
                    anchored.append({"path": f["file"], "line": f["line"], "severity": f["severity"], "body": f"**{f['tool']} {f['code']}**: {f['message']}", "source": f["tool"]})
            summary = res["summary"] or "Automatic findings only."
            if loose:
                summary += "\n\nAlso noted (not attached to a diff line):\n" + "\n".join(f"- `{c['path']}`" + (f":{c['line']}" if c["line"] else "") + f" {c['body'][:300]}" for c in loose[:8])
            verdict = res["verdict"]
            if verdict == "approve" and any(c["severity"] == "high" for c in anchored):
                verdict = "comment"
            anchored = anchored[:25]
            report = {"kind": "review", "verdict": verdict, "summary": summary, "comments": anchored, "static_findings": len(static), "static_note": static_note, "head_sha": pr["pr"]["head_sha"],
                      "number": pr["pr"]["number"]}
        else:
            conc = [c for c in res["concerns"]] + [{"file": f["file"], "line": f["line"], "severity": "high" if f["severity"] in ("critical", "high") else "medium" if f["severity"] == "medium" else "low",
                                                    "message": f"[{f['tool']} {f['code']}] {f['message']}"} for f in static[:10]]
            report = {"kind": "analysis", **{k: res[k] for k in ("summary", "change_type", "risk", "risk_reasons", "key_changes", "impact", "test_assessment", "questions")}, "concerns": conc[:20],
                      "static_note": static_note, "suggested_reviewers": pr.get("suggested_reviewers", []), "tests_touched": tests_touched, "number": pr["pr"]["number"],
                      "files": [{"path": f["path"], "status": f["status"], "additions": f["additions"], "deletions": f["deletions"]} for f in pr["files"]]}
        return {"pr_report": report, "steps": log(st, "review", f"{'review draft' if review else 'analysis'} of PR #{pr['pr']['number']}: " + static_note + degraded)}


class Reviewer(Base):
    def review_patch(self, st: AgentState) -> dict:
        rounds = st["review_rounds"] + 1
        static = []
        for f, text in st["final_files"].items():
            static += static_checks(f, text)
        # a patch that hides the error (swallowing handlers, lint suppression) is rejected without a model call
        originals = {}
        for f in st["final_files"]:
            try:
                originals[f] = self.tools.read_file(f)
            except (ValueError, OSError):
                originals[f] = ""
        guard = suppression_findings(originals, st["final_files"])
        static += guard
        blockers = [x for x in static if x["severity"] == "high" and ("Syntax error" in x["message"] or "eval" in x["message"] or "secret" in x["message"] or x.get("source") == "patch-guard")]
        if blockers:   # no model needed to reject a patch that does not parse
            fb = "; ".join(f"{b['file']}:{b['line']} {b['message']}" for b in blockers[:3])
            return {"review": {"approved": False, "summary": "automatic checks failed", "feedback": fb, "findings": blockers[:5]}, "review_rounds": rounds,
                    "steps": log(st, "review", f"rejected by automatic checks: {fb[:160]}")}
        ta = st.get("test_after")

        def build(_b: int) -> str:
            return (f"Problem / request:\n{st['question'][:1500]}\nAnalysis: {_brief(st.get('analysis') or {})}\n\nProposed patch:\n```diff\n{st['diff'][:5000]}```\n"
                    f"Test result after patch: {ta['status'] + ' (' + ta['summary'] + ')' if ta else 'not run'}\n"
                    f"Automatic checks: {[x['message'] for x in static if x['severity'] != 'low'][:5] or 'nothing flagged'}\n\n"
                    'Return JSON: {"approved": bool, "summary": "one sentence verdict", "feedback": "what to change if not approved", '
                    '"findings": [{"file": "", "line": 0, "severity": "high|medium|low", "confidence": "high|medium|low", "message": "", "evidence": "the code line", "fix": "how to remediate"}]}')
        degraded = ""
        try:
            res = self.json("review_patch", prompts.REVIEW_PATCH, build, schemas.Review)
        except LLMBudgetExceeded:
            raise
        except LLMError as e:
            res, degraded = schemas.Review().model_dump(), f" (model unavailable: {type(e).__name__}; not reviewed by a model)"
        res["findings"] = dedupe_findings(static + [dict(f, source="ai") for f in res["findings"]])[:8]
        verdict = "approved" if res["approved"] else f"changes requested: {(res['feedback'] or res['summary'])[:140]}"
        return {"review": res, "review_rounds": rounds, "steps": log(st, "review", verdict + degraded)}

    def review_code(self, st: AgentState) -> dict:
        tools = self.tools
        target = st.get("target") or ""
        from ..review.engine import review_project
        # every analysable file is checked with the strict engine (no sampling); the model only reads a few files for deeper reasoning
        res_static = review_project(tools.root, only=[target] if target else None)
        findings = [{"file": f["file"], "line": f["line"], "severity": f["severity"], "confidence": f["confidence"], "message": f"{f['message']} [{f['rule']}]", "evidence": f["evidence"], "fix": f["fix"], "source": "static"}
                    for f in res_static["findings"]]
        files = [target] if target else [f for f in tools.index.tree if f.endswith((".py", ".js", ".ts"))][:40]
        texts = {}
        for f in files:
            try:
                texts[f] = tools.read_file(f)
            except (ValueError, OSError):
                continue
        focus = [target] if target else list(dict.fromkeys(c["file"] for c in st.get("context", []) if c["file"] in texts))[:6] or list(texts)[:6]
        code = "\n\n".join(f"### {f}\n```\n{texts[f][:2500]}\n```" for f in focus if f in texts)

        def build(_b: int) -> str:
            return ("Review this code for bugs, security problems, error handling and maintainability. Only report real issues you can point to.\n\n"
                    f"{code}\n\n" + 'Return JSON: {"summary": "2-3 sentences", "findings": [{"file": "path", "line": 1, "severity": "high|medium|low", "confidence": "high|medium|low", '
                    '"message": "the issue", "evidence": "the exact code line", "fix": "concrete remediation"}]}')
        degraded = ""
        try:
            res = self.json("review", prompts.REVIEW_CODE, build, schemas.Review)
        except LLMBudgetExceeded:
            raise
        except LLMError as e:
            res, degraded = schemas.Review().model_dump(), f" (model unavailable: {type(e).__name__}; automatic checks only)"
        ai = ground_findings([{**f, "source": "ai", "line": f["line"] or 0} for f in res["findings"] if f["message"]], texts)
        findings = dedupe_findings(findings + ai)
        n = len(findings)
        summary = res["summary"] or f"{n} issue{'s' * (n != 1)} found by automatic checks in {len(texts)} file{'s' * (len(texts) != 1)}."
        return {"review_report": {"summary": summary, "findings": findings},
                "steps": log(st, "review", f"scanned {len(texts)} files; {n} findings" + degraded)}


# ======================================================================================================
class Documenter(Base):
    def describe(self, st: AgentState) -> dict:
        idx = self.tools.index
        folders: dict[str, int] = {}
        for f in idx.tree:
            top = f.split("/")[0] if "/" in f else "(root)"
            folders[top] = folders.get(top, 0) + 1
        routes = sorted({f"{c.route} → {c.file}::{c.name}" for c in idx.chunks if c.route})
        edges = [f"{f} → {t}" for f in idx.imports for t in self.tools.get_dependencies(f)["internal_files"] if t != f]
        facts = {"folders": folders, "routes": routes[:40], "imports": edges[:60], "dependencies": idx.deps}
        try:
            readme = self.tools.read_file("README.md")[:1500]
        except (ValueError, OSError):
            readme = ""

        def build(_b: int) -> str:
            return (f"README:\n{readme}\n\nFacts extracted from the code:\n{facts}\n\n"
                    + (f"Question: {st['question'][:500]}\n\n" if st["mode"] != "architecture" else "")
                    + "Explain the architecture for a new engineer: purpose, main components and what each does, how a request or data flows through them, "
                      'and key dependencies. Return JSON: {"summary": "markdown"}')
        degraded = ""
        try:
            res = self.json("document", prompts.DOCUMENT, build, schemas.Docs, hints={})
        except LLMBudgetExceeded:
            raise
        except LLMError as e:
            res, degraded = schemas.Docs().model_dump(), f" (model unavailable: {type(e).__name__})"
        fallback = ("**Structure**\n" + "\n".join(f"- `{k}`: {v} files" for k, v in folders.items())
                    + ("\n\n**Routes**\n" + "\n".join(f"- `{r}`" for r in routes[:15]) if routes else "")
                    + ("\n\n**Internal imports**\n" + "\n".join(f"- `{e}`" for e in edges[:15]) if edges else "")
                    + "\n\n_(Connect an AI model for a written explanation of how these parts fit together.)_")
        steps = log(st, "inspect", f"{len(idx.tree)} files, {len(routes)} routes, {len(edges)} internal imports")
        steps = steps + [{"node": "explain", "message": "wrote the overview" + degraded}]
        return {"docs": res["summary"] or fallback, "facts": facts, "steps": steps}

    def change_notes(self, st: AgentState) -> dict:
        def build(_b: int) -> str:
            return (f"Change made:\n{st.get('explanation', '')}\n```diff\n{st['diff'][:3500]}```\n\n"
                    'Return JSON: {"summary": "2-3 sentences of documentation to add or update, naming the file", "changelog": "one changelog line"}')
        try:
            res = self.json("document", prompts.DOCUMENT, build, schemas.Docs)
        except LLMBudgetExceeded:
            raise
        except LLMError:
            res = schemas.Docs().model_dump()
        text = "\n".join(x for x in (res["summary"], f"Changelog: {res['changelog']}" if res["changelog"] else "") if x)
        return {"docs": text, "steps": log(st, "document", "wrote change notes" if text else "no documentation notes")}
