import type { AgentEvent, Run } from "./types";

const NODE: Record<string, string> = {
  understand: "Planner: understanding the task", plan: "Planner: choosing specialists", research: "Researcher: gathering code",
  analyze: "Debugger: reasoning about the code", code: "Coder: writing the change", test: "Tester: running the tests",
  reflect: "Debugger: working out what went wrong", review: "Reviewer: checking the work", document: "Documenter: writing it up",
  respond: "Writing the answer",
};
const TOOL: Record<string, string> = {
  search_code: "Search code", read_file: "Read file", related: "Follow call graph", find_symbol: "Look up symbol",
  run_tests: "Run tests", get_dependencies: "Read dependencies", list_tree: "List files",
  grep: "Exact text search", callers: "Find callers", callees: "Find callees", impact: "Impact analysis", list_files: "List files",
  git_status: "Git status", git_branches: "Git branches", git_show: "Show commit", git_blame: "Git blame", git_file_at: "Previous version", git_changed_files: "Changed files", git_authors: "Authors", git_history: "Git history", git_log: "Git history", git_diff: "Git diff", search_docs: "Search documentation", find_config: "Inspect configuration",
  inspect_project: "Inspect project", search_web: "Search the web", lint: "Run linter", check_patch: "Check patch in sandbox",
};
const TASK: Record<string, string> = {
  understand: "understand the task", plan: "plan the work", research: "pick tools", analyze: "analyse retrieved code",
  generate_fix: "write patch", generate_change: "write change", generate_tests: "write tests", reflect: "diagnose the failure",
  review_patch: "review the patch", review: "review code", document: "write documentation",
};

export const nodeLabel = (n: string) => NODE[n] ?? n;
export const toolLabel = (n: string) => TOOL[n] ?? n;
export const taskLabel = (n: string) => TASK[n] ?? n;

/** The one-line "what is it doing right now" text, from the newest event. */
export function currentActivity(run?: Run): string {
  if (!run) return "Starting…";
  for (let i = run.events.length - 1; i >= 0; i--) {
    const e = run.events[i];
    if (e.type === "status") return e.message;
    if (e.type === "tool" && e.phase === "start") return `${toolLabel(e.name)}${e.args ? `: ${e.args}` : ""}`;
    if (e.type === "llm" && e.phase === "start") return `Asking ${e.model} to ${taskLabel(e.task)}`;
    if (e.type === "node" && e.phase === "start") return nodeLabel(e.node);
    if (e.type === "step") return e.message;
  }
  return "Starting…";
}

export interface Row {
  key: string; kind: "node" | "tool" | "llm" | "step" | "status" | "result" | "error" | "run";
  title: string; detail?: string; ms?: number; state: "running" | "done" | "error"; t: number; depth: number; hits?: { file: string; lines: string; symbol: string }[];
}

/** Collapse raw start/end events into one row per action for the Agent Activity timeline. */
export function toRows(run: Run): Row[] {
  const rows: Row[] = [];
  const open = new Map<string, number>();
  let depth = 0;
  const t0 = run.started / 1000;
  const t = (e: AgentEvent) => Math.max(0, e.ts - t0);
  for (const e of run.events) {
    switch (e.type) {
      case "run_start": rows.push({ key: `r${e.seq}`, kind: "run", title: `Run started`, detail: run.label, state: "done", t: t(e), depth: 0 }); break;
      case "node":
        if (e.phase === "start") { open.set(`n:${e.node}`, rows.length); rows.push({ key: `n${e.seq}`, kind: "node", title: nodeLabel(e.node), state: "running", t: t(e), depth: 0 }); depth = 1; }
        else { const i = open.get(`n:${e.node}`); if (i != null) rows[i] = { ...rows[i], state: "done", ms: Math.round((e.ts - (t0 + rows[i].t)) * 1000) }; depth = 0; }
        break;
      case "tool": {
        const k = `t:${e.name}:${e.args}`;
        if (e.phase === "start") { open.set(k, rows.length); rows.push({ key: `t${e.seq}`, kind: "tool", title: toolLabel(e.name), detail: e.args, state: "running", t: t(e), depth }); }
        else { const i = open.get(k); const row = { title: toolLabel(e.name), detail: e.error ?? e.summary ?? e.args, ms: e.ms, state: e.phase === "error" ? "error" as const : "done" as const, hits: e.hits };
          if (i != null) rows[i] = { ...rows[i], ...row }; else rows.push({ key: `t${e.seq}`, kind: "tool", t: t(e), depth, ...row }); }
        break;
      }
      case "llm": {
        const k = `l:${e.task}`;
        if (e.phase === "start") { open.set(k, rows.length); rows.push({ key: `l${e.seq}`, kind: "llm", title: `Model (${e.model}): ${taskLabel(e.task)}`, detail: e.prompt_chars ? `${Math.round(e.prompt_chars / 3.5).toLocaleString()} tokens of context (approx.)` : undefined, state: "running", t: t(e), depth }); }
        else { const i = open.get(k); if (i != null) rows[i] = { ...rows[i], state: e.phase === "error" ? "error" : "done", ms: e.ms, detail: e.error ?? (e.input_tokens != null ? `${e.input_tokens.toLocaleString()} in / ${(e.output_tokens ?? 0).toLocaleString()} out tokens${e.tool_calls ? `, ${e.tool_calls} tool call(s)` : ""}` : rows[i].detail) }; }
        break;
      }
      case "step": rows.push({ key: `s${e.seq}`, kind: "step", title: e.message, detail: e.node, state: "done", t: t(e), depth }); break;
      case "status": rows.push({ key: `u${e.seq}`, kind: "status", title: e.message, state: "running", t: t(e), depth }); break;
      case "result": rows.push({ key: `x${e.seq}`, kind: "result", title: "Finished", detail: e.data.status, state: "done", t: t(e), depth: 0 }); break;
      case "error": rows.push({ key: `e${e.seq}`, kind: "error", title: e.message, state: "error", t: t(e), depth: 0 }); break;
    }
  }
  // transient status lines are done once anything newer happened
  rows.forEach((r, i) => { if (r.kind === "status" && i < rows.length - 1) r.state = "done"; });
  if (run.state !== "running") rows.forEach((r) => { if (r.state === "running") r.state = run.state === "done" ? "done" : "error"; });
  return rows;
}
