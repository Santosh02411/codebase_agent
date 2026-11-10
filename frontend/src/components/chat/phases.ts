import type { Run } from "@/lib/types";

export const PHASES = [
  { key: "understand", label: "Understand", nodes: ["understand"] },
  { key: "plan", label: "Plan", nodes: ["plan"] },
  { key: "research", label: "Research", nodes: ["research"] },
  { key: "analyze", label: "Analyze", nodes: ["analyze", "reflect"] },
  { key: "implement", label: "Implement", nodes: ["code"] },
  { key: "test", label: "Test", nodes: ["test"] },
  { key: "review", label: "Review", nodes: ["review", "pr", "document"] },
  { key: "complete", label: "Complete", nodes: ["respond"] },
] as const;

export type PhaseState = "pending" | "running" | "done" | "skipped" | "error";
export interface PhaseInfo { key: string; label: string; state: PhaseState; visits: number; ms: number }

/** Phase status derived ONLY from real `node` events of the run. A phase that never started is "pending" while the run is live and
 *  "skipped" once it finished (a question never reaches the coder): nothing is shown as done unless the backend reported it. */
export function derivePhases(run?: Run, now = Date.now()): PhaseInfo[] {
  const phases: PhaseInfo[] = PHASES.map((p) => ({ key: p.key, label: p.label, state: "pending", visits: 0, ms: 0 }));
  if (!run) return phases;
  const byNode = new Map<string, number>(PHASES.flatMap((p, i) => p.nodes.map((n) => [n, i] as [string, number])));
  const open = new Map<string, number>();
  for (const e of run.events) {
    if (e.type !== "node") continue;
    const i = byNode.get(e.node);
    if (i == null) continue;
    const ph = phases[i];
    if (e.phase === "start") { ph.visits++; ph.state = "running"; open.set(e.node, e.ts * 1000); }
    else { const t0 = open.get(e.node); if (t0 != null) ph.ms += Math.max(0, e.ts * 1000 - t0); open.delete(e.node); if (![...open.keys()].some((n) => byNode.get(n) === i)) ph.state = "done"; }
  }
  for (const [node, t0] of open) { const i = byNode.get(node)!; phases[i].ms += Math.max(0, now - t0); }
  const failed = run.state === "error";
  const lastRunning = phases.findIndex((p) => p.state === "running");
  if (run.state !== "running") {
    phases.forEach((p) => { if (p.state === "running") p.state = failed ? "error" : "done"; else if (p.state === "pending") p.state = "skipped"; });
    if (run.state === "done") phases[phases.length - 1].state = "done";   // the result event arrived
    if (failed && lastRunning < 0) { const last = [...phases].reverse().find((p) => p.visits > 0); if (last) last.state = "error"; }
  }
  return phases;
}
