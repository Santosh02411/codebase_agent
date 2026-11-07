"""Graph nodes and routing. A node takes the state and returns a partial update; `route` decides what runs next from the plan and
from what has happened so far. The same nodes drive LangGraph (graph.py) or the built-in runner."""
from __future__ import annotations
import threading
import time
from ..config import Settings
from ..llm import LLM
from ..rag.context import check_file_refs, extract_citations
from . import prompts
from .context import ContextBuilder
from .. import verify
from .errors import ErrorReport
from .memory import ConversationStore
from .registry import ToolRegistry
from .specialists import Coder, Debugger, Documenter, PRReviewer, Planner, Researcher, Reviewer, Tester
from .state import AgentState, log
from .tools import RepoTools

END = "__end__"
SYSTEM = prompts.BASE
STATUS_OF = {"resolved": "fix_verified", "partial": "fix_verified", "no_regressions": "fix_verified", "unverified": "fix_unverified", "not_resolved": "fix_failed"}
VERDICT_LINE = {"resolved": "✅ **Resolved.**", "partial": "⚠️ **Partially resolved.**", "no_regressions": "✅ **No regressions.**",
                "unverified": "⚠️ **Not verified.**", "not_resolved": "❌ **Not resolved.**"}
AGENT_OF = {"pr": "reviewer", "understand": "planner", "plan": "planner", "research": "researcher", "analyze": "debugger", "code": "coder", "test": "tester",
            "reflect": "debugger", "review": "reviewer", "document": "documenter", "respond": "supervisor"}


class AgentRuntime:
    def __init__(self, llm: LLM, tools: RepoTools, settings: Settings, store: ConversationStore | None = None) -> None:
        self.llm, self.tools, self.s = llm, tools, settings
        self.store = store or ConversationStore(None)
        self.registry = ToolRegistry(tools)
        self.ctx = ContextBuilder(tools, settings)
        self.planner, self.researcher, self.debugger = Planner(self), Researcher(self), Debugger(self)
        self.coder, self.tester, self.reviewer, self.documenter = Coder(self), Tester(self), Reviewer(self), Documenter(self)
        self.pr_reviewer = PRReviewer(self)
        limit = getattr(settings, "max_run_seconds", 0) or 0
        self.deadline = (time.monotonic() + limit) if limit > 0 else None   # wall-clock limit for the whole run
        self.cancel = threading.Event()                                    # set() from another thread to stop the run at the next node

    # ---- nodes -------------------------------------------------------------------------------
    def understand(self, st: AgentState) -> dict:
        return self.planner.understand(st)

    def plan(self, st: AgentState) -> dict:
        return self.planner.plan(st)

    def research(self, st: AgentState) -> dict:
        return self.researcher.run(st)

    def analyze(self, st: AgentState) -> dict:
        return self.debugger.run(st)

    def code(self, st: AgentState) -> dict:
        return self.coder.run(st)

    def test(self, st: AgentState) -> dict:
        return self.tester.run(st)

    def reflect(self, st: AgentState) -> dict:
        return self.tester.reflect(st)

    def review(self, st: AgentState) -> dict:
        return self.reviewer.review_code(st) if st["intent"] == "review" else self.reviewer.review_patch(st)

    def pr(self, st: AgentState) -> dict:
        return self.pr_reviewer.run(st)

    def document(self, st: AgentState) -> dict:
        return self.documenter.describe(st) if st["intent"] == "docs" else self.documenter.change_notes(st)

    # ---- the final report --------------------------------------------------------------------------------
    def affected_files(self, st: AgentState) -> list[dict]:
        """Every file involved, once, with why: where it failed, the root cause, the call stack, callers, what the patch touches."""
        order: dict[str, dict] = {}

        def add(path: str, role: str, detail: str = "") -> None:
            if path:
                e = order.setdefault(path, {"path": path, "roles": [], "detail": ""})
                if role not in e["roles"]:
                    e["roles"].append(role)
                e["detail"] = e["detail"] or detail

        rep, a = st.get("error_report") or {}, st.get("analysis") or {}
        if rep.get("file"):
            add(rep["file"], "failure point", f"line {rep['line']}" + (f" in {rep['function']}()" if rep.get("function") else ""))
        if a.get("affected_file"):
            add(a["affected_file"], "root cause", f"{a['affected_function']}()" if a.get("affected_function") else "")
        for f in (rep.get("frames") or [])[:-1]:
            add(f["file"], "call stack", f"{f['func']}() line {f['line']}" if f.get("func") else f"line {f['line']}")
        fn = a.get("affected_function") or rep.get("function")
        if fn and st["intent"] == "debug":
            for c in self.tools.callers(fn.split(".")[-1])[:3]:
                add(c["file"], "caller", f"{c['caller']}()")
        for f in st.get("patch_files", []):
            add(f["path"], {"create": "added", "delete": "deleted"}.get(f["op"], "modified"), f"+{f['additions']}/-{f['deletions']}")
        return list(order.values())

    def _tests_executed(self, st: AgentState) -> str:
        tb, ta = st.get("test_before"), st.get("test_after")
        if tb is None and ta is None:
            return "Tests were not run for this request. Use **Debug** (not Generate Fix) to have the fix verified automatically."
        rows = []
        def run_line(label: str, t: dict) -> str:
            fails = ", ".join(f"`{x['id']}`" for x in t.get("failed_tests", [])[:4])
            return f"- {label}: **{t['status'].replace('_', ' ')}** — {t['summary']}" + (f" (failing: {fails})" if fails else "") + (f" · `{t['command']}`" if t.get("command") else "")
        if tb:
            rows.append(run_line("Before the fix", tb))
        rg = st.get("regression")
        if rg:
            rows.append(f"- Regression test added: `{', '.join(rg['tests'])}` — " + ("**fails on the original code** (it reproduces the problem)" if rg["failed_before"] else "passes on the original code (it does **not** reproduce the problem)")
                        + (", **passes with the fix**" if rg["passed_after"] else f", still fails with the fix ({', '.join(rg.get('after_failed', [])[:2])})"))
        if ta:
            rows.append(run_line("After the fix", ta))
        la = st.get("lint_after")
        if la:
            new = st.get("lint_new", [])
            blocking = [i for i in new if i.get("blocking")]
            rows.append(f"- Linter ({la['tool']}): " + ("no new findings" if not new else f"{len(new)} new finding(s), **{len(blocking)} blocking**"
                        + "".join(f"\n  - `{i['file']}:{i['line']}` {i['code']} {i['message'][:90]}" for i in new[:4])))
        return "\n".join(rows)

    def _debug_report(self, st: AgentState, status: str) -> str:
        a, rep = st.get("analysis") or {}, ErrorReport(**{k: v for k, v in (st.get("error_report") or {}).items() if k in ErrorReport.__dataclass_fields__})
        out: list[str] = []
        cause = [f"**Exception:** `{rep.exception_type}`" + (f" — {rep.message}" if rep.message else "") + (f" ({rep.category})" if rep.category else "")] if rep.exception_type else []
        if rep.file:
            cause.append(f"**Location:** `{rep.file}:{rep.line}`" + (f" in `{rep.function}()`" if rep.function else "") + (f"\n`{rep.code_line}`" if rep.code_line else ""))
        if rep.variables:
            cause.append("**Variable:** " + ", ".join(f"`{v['name']}` ({v['evidence']})" for v in rep.variables[:3]))
        out.append("## Root Cause\n" + "\n\n".join(cause + [a.get("root_cause") or a.get("answer") or "The cause could not be determined from the retrieved code."]))
        files = st.get("affected_files") or []
        out.append("## Affected Files\n" + ("\n".join(f"- `{f['path']}` — {', '.join(f['roles'])}" + (f" ({f['detail']})" if f["detail"] else "") for f in files) or "None identified."))
        expl = [x for x in (a.get("answer") if a.get("root_cause") else "", st.get("explanation")) if x]
        if rep.frames:
            expl.append("**How it fails:** " + " → ".join(f"`{f['func'] or f['file']}()`" for f in rep.frames[-5:]) + (f" → `{rep.exception_type}`" if rep.exception_type else ""))
        out.append("## Explanation\n" + ("\n\n".join(expl) or "See the root cause above."))
        if st["plan"].get("needs_patch"):
            if st["patch_files"]:
                out.append(f"## Proposed Fix\n```diff\n{st['diff']}```\nReview the exact diff and approve it to apply it to the project.")
            else:
                out.append("## Proposed Fix\n_No patch was generated._ " + (st["fix_error"] or ""))
            out.append("## Tests Executed\n" + (self._tests_executed(st) if st["patch_files"] else "Nothing to test: there is no patch."))
            v = st.get("verification")
            if not st["patch_files"]:
                out.append("## Verification Result\n❌ **Not resolved.** No fix could be produced.")
            elif v is None:
                out.append("## Verification Result\n⚠️ **Not verified.** Tests were not run for this request.")
            else:
                lines = [f"{VERDICT_LINE[v['status']]} {v['summary'][0].upper() + v['summary'][1:]}."]
                if v["status"] == "not_resolved":
                    lines.append(f"The agent tried {st['attempts']} time(s).")
                lines += [f"- {r}" for r in v.get("reasons", [])[:4] if r]
                rv = st.get("review")
                if rv and rv.get("summary"):
                    lines.append(f"Reviewer: {'approved' if rv.get('approved') else 'concerns remain'} — {rv['summary']}" + (f" {rv['feedback']}" if not rv.get("approved") and rv.get("feedback") else ""))
                out.append("## Verification Result\n" + "\n".join(lines))
        return "\n\n".join(out)

    @staticmethod
    def _pr_text(r: dict) -> str:
        if r["kind"] == "review":
            head = {"approve": "✅ Approve", "comment": "💬 Comment", "request_changes": "❌ Request changes"}[r["verdict"]]
            by_file: dict[str, list[dict]] = {}
            for c in r["comments"]:
                by_file.setdefault(c["path"], []).append(c)
            body = "\n".join(f"**`{p}`**\n" + "\n".join(f"- line {c['line']} · **{c['severity']}** — {c['body']}" for c in cs) for p, cs in by_file.items())
            return (f"## Review of PR #{r['number']}\n**Verdict:** {head}\n\n{r['summary']}\n\n" + (body + "\n\n" if body else "") +
                    f"_{r['static_note']}_\n\n> This is a **draft**. Nothing has been posted to GitHub: posting needs your approval.")
        risk = {"low": "🟢 low", "medium": "🟡 medium", "high": "🔴 high"}[r["risk"]]
        out = [f"## Pull request #{r['number']}\n{r['summary']}", f"**Type:** {r['change_type']} · **Risk:** {risk}" + ("".join(f"\n- {x}" for x in r["risk_reasons"]))]
        if r["key_changes"]:
            out.append("## Key Changes\n" + "\n".join(f"- `{c.get('file', '')}` — {c.get('what', '')}" for c in r["key_changes"]))
        if r["impact"]:
            out.append("## Impact\n" + "\n".join(f"- {x}" for x in r["impact"]))
        out.append("## Tests\n" + (r["test_assessment"] or "Not assessed.") + (f"\nTest files changed: {', '.join('`' + t + '`' for t in r['tests_touched'])}" if r["tests_touched"] else "\nNo test files changed."))
        if r["concerns"]:
            out.append("## Concerns\n" + "\n".join(f"- **{c['severity']}** `{c['file']}`" + (f":{c['line']}" if c["line"] else "") + f" — {c['message']}" for c in r["concerns"]))
        if r["questions"]:
            out.append("## Questions for the Author\n" + "\n".join(f"- {q}" for q in r["questions"]))
        if r["suggested_reviewers"]:
            out.append("## Suggested Reviewers\n" + ", ".join(f"{x['author']} ({x['commits']} commits on these files)" for x in r["suggested_reviewers"]))
        out.append(f"_{r['static_note']}_")
        return "\n\n".join(out)

    def _tests_report(self, st: AgentState) -> str:
        """Report for generated tests: what was written, how it follows the repository's conventions, how it ran, what coverage changed."""
        out: list[str] = []
        pat = st.get("test_patterns") or {}
        new = [f for f in st["patch_files"] if f["op"] == "create"]
        out.append("## Generated Tests\n" + (f"{len(new)} new test file(s): " + ", ".join(f"`{f['path']}` (+{f['additions']} lines)" for f in new) if new else "No test file was produced.")
                   + (f"\nFramework: **{pat['framework']}**" + (f"; conventions followed: {pat['layout']}" if pat.get("layout") else "") + (f"; assertions: {pat['assertions']}" if pat.get("assertions") else "")
                      + (f"; mocking: {', '.join(pat['mocking'])}" if pat.get("mocking") else "") if pat.get("framework") else ""))
        if st.get("explanation"):
            out.append("## What the Tests Cover\n" + st["explanation"])
        if st["patch_files"]:
            out.append(f"## Proposed Change\n```diff\n{st['diff']}```")
            out.append("## Tests Executed\n" + self._tests_executed(st))
            cd = st.get("coverage_delta")
            if cd:
                rows = "".join(f"\n- `{f['path']}`: {f['before']}% → **{f['after']}%**" + (f" (still uncovered: lines {', '.join(f['missing'][:4])})" if f["missing"] else "") for f in cd["files"][:6])
                out.append(f"## Coverage\nOverall: {cd['before']}% → **{cd['after']}%**{rows}")
            if st.get("impl_change"):
                impl = [f["path"] for f in st["patch_files"] if not verify.is_test_file(f["path"])]
                out.append("## ⚠ Implementation Changed\nA generated test failed because of what looks like a **bug in the code under test**, so this patch also changes "
                           f"{', '.join('`' + p + '`' for p in impl)}. Review that change as carefully as any bug fix: the test encodes what the model believes is correct behaviour.")
            v = st.get("verification")
            out.append("## Verification Result\n" + (f"{VERDICT_LINE[v['status']]} {v['summary']}" if v else "⚠️ **Not verified.** Tests were not run for this request."))
        return "\n\n".join(out)

    def respond(self, st: AgentState) -> dict:
        a, parts, intent = st.get("analysis") or {}, [], st["intent"]
        status = "answered"
        extra: dict = {}
        if st.get("error"):
            parts.append(f"**The model call failed:** {st['error']}")
            status = "error"
        if intent in ("debug", "change", "tests") and status != "error":
            extra["affected_files"] = st["affected_files"] = self.affected_files(st) if intent == "debug" else []
        if intent == "pr" and st.get("pr_report"):
            parts.append(self._pr_text(st["pr_report"]))
            status = status if status == "error" else "reviewed"
        elif intent == "review" and st.get("review_report"):
            rr = st["review_report"]
            parts.append(rr["summary"])
            parts += [f"- **{f['severity']}** `{f['file']}`" + (f":{f['line']}" if f.get("line") else "") + f" — {f['message']}" for f in rr["findings"][:30]]
            status = status if status == "error" else "reviewed"
        elif intent == "docs":
            parts.append(st.get("docs") or "No documentation produced.")
        else:
            patch_status = None
            if st["plan"].get("needs_patch") and status != "error":
                if st["patch_files"]:
                    v = st.get("verification")
                    patch_status = STATUS_OF[v["status"]] if v else "fix_unverified"
                else:
                    patch_status = "no_fix"
                status = patch_status
            if intent == "tests" and status != "error":
                parts.append(self._tests_report(st))
            elif intent == "debug" and st["plan"].get("needs_patch") and status != "error":
                parts.append(self._debug_report(st, status))
            else:
                if a.get("root_cause"):
                    parts.append(f"**Root cause**\n{a['root_cause']}")
                if a.get("answer"):
                    parts.append(f"**Analysis**\n{a['answer']}")
                if a.get("affected_file"):
                    parts.append(f"**Affected:** `{a['affected_file']}`" + (f" → `{a['affected_function']}()`" if a.get("affected_function") else ""))
                if st["plan"].get("needs_patch") and status != "error":
                    if st["patch_files"]:
                        if st.get("explanation"):
                            parts.append(f"**What changed**\n{st['explanation']}")
                        parts.append(f"**Proposed change**\n```diff\n{st['diff']}```")
                        parts.append(f"**Tests executed**\n{self._tests_executed(st)}")
                        v = st.get("verification")
                        if v:
                            parts.append(f"**Verification:** {VERDICT_LINE[v['status']]} {v['summary']}")
                        rv = st.get("review")
                        if rv and rv.get("summary"):
                            parts.append(f"**Review:** {'approved' if rv.get('approved') else 'concerns remain'} — {rv['summary']}" + (f" {rv['feedback']}" if not rv.get("approved") and rv.get("feedback") else ""))
                    else:
                        parts.append(f"_No patch generated._ {st['fix_error']}".strip())
            if st.get("docs") and st["plan"].get("needs_docs"):
                parts.append(f"**Documentation**\n{st['docs']}")
        answer = "\n\n".join(p for p in parts if p) or "No answer produced."
        claim_text = f"{a.get('answer', '')} {a.get('root_cause', '')} {a.get('explanation', '')}"
        cites = extract_citations(claim_text, len(st["context"]))
        refs = check_file_refs(claim_text, st["context"], self._line_count)
        if refs["invalid"] or refs["unretrieved"] or refs["grounded"]:   # added only when the answer names file:line, so the response shape is unchanged otherwise
            cites["references"] = {k: v for k, v in refs.items() if v}
        note = (f", cited {len(cites['cited'])}/{len(st['context'])} snippets" + (f", {len(cites['invalid'])} invalid citation(s)" if cites["invalid"] else "")
                + (f", {len(refs['invalid'])} file:line reference(s) not found in the repository" if refs["invalid"] else ""))
        if refs["invalid"]:
            answer += "\n\n_Warning: these file:line references could not be matched to the repository and should not be trusted: " + ", ".join(refs["invalid"][:6]) + "._"
        if st.get("conversation_id"):
            files = list(dict.fromkeys(([a["affected_file"]] if a.get("affected_file") else []) + list(st.get("final_files", {}))))
            self.store.append(st["conversation_id"], {"question": st["question"][:400], "intent": intent, "status": status, "files": files[:6],
                                                      "summary": (a.get("answer") or a.get("root_cause") or st.get("explanation") or answer)[:500]})
        return {"answer": answer, "status": status, "citations": cites, "steps": log(st, "respond", f"status={status}{note}"), **extra}

    def _line_count(self, path: str):
        """Length of a repository file in lines, or None when the file does not exist / cannot be read (used to validate file:line claims)."""
        try:
            return len(self.tools.read_file(path).splitlines())
        except (ValueError, OSError, UnicodeDecodeError):
            return None

    # ---- routing -----------------------------------------------------------------------------
    def route(self, node: str, st: AgentState) -> str:
        if node == "respond":
            return END
        if st.get("error") or st.get("step_count", 0) >= self.s.max_agent_total_steps:
            return "respond"
        plan, intent = st.get("plan") or {}, st.get("intent", "explain")
        if node == "understand":
            return "plan"
        if node == "plan":
            return "research"
        if node == "research":
            if intent == "pr":
                return "pr"
            if intent == "review":
                return "review"
            if intent == "docs":
                return "document"
            if intent == "tests":
                return "code" if plan.get("needs_patch") else "respond"
            return "analyze"
        if node == "analyze":
            if st["need_more"]:
                return "research"
            return "code" if plan.get("needs_patch") else "respond"
        if node == "code":
            if st["fix_error"]:               # the latest attempt was rejected by the patch engine / checks: try again with that feedback
                return "code" if (st["proposed"] and st["attempts"] < self.s.max_fix_attempts) else "respond"
            return "test" if plan.get("needs_tester") else self._after_patch(st)
        if node == "test":
            if (st.get("verification") or {}).get("status") == "not_resolved":
                return "reflect" if st["attempts"] < self.s.max_fix_attempts else "respond"
            return self._after_patch(st)
        if node == "pr":
            return "respond"
        if node == "reflect":
            rf = st.get("reflection") or {}
            return "respond" if rf.get("action") == "stop" else "research" if rf.get("action") == "research_more" else "code"
        if node == "review":
            if intent == "review":
                return "respond"
            rv = st.get("review") or {}
            if not rv.get("approved", True) and st["review_rounds"] < 2 and st["attempts"] < self.s.max_fix_attempts:
                return "code"
            return "document" if plan.get("needs_docs") else "respond"
        return "respond"

    @staticmethod
    def _after_patch(st: AgentState) -> str:
        plan = st.get("plan") or {}
        if plan.get("needs_review") and st["review_rounds"] < 2:
            return "review"
        return "document" if plan.get("needs_docs") else "respond"
