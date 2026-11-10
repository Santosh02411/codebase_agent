"use client";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bug, FlaskConical, Gauge, Loader2, Lock, Play, ShieldAlert, ShieldCheck, Wrench } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { QAnalyzer, QFinding, QualityReport, Severity } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useIde } from "@/store/ide";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

const SEV_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];
const SEV_BADGE: Record<Severity, "destructive" | "warning" | "secondary" | "outline"> = { critical: "destructive", high: "destructive", medium: "warning", low: "secondary", info: "outline" };
const GRADE_COLOR: Record<string, string> = { A: "text-emerald-400", B: "text-lime-400", C: "text-amber-300", D: "text-orange-400", F: "text-red-400", "n/a": "text-muted-foreground" };
const DIM_LABEL: Record<string, string> = { tests: "Tests", coverage: "Coverage", lint: "Lint", types: "Types", security: "Security", maintainability: "Maintainability" };

export function SandboxBadge() {
  const q = useQuery({ queryKey: ["sandbox"], queryFn: api.sandbox, staleTime: 30_000, retry: false });
  if (!q.data) return null;
  const s = q.data;
  const ok = s.isolated && s.docker_available !== false;
  return (
    <span className={cn("flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px]", ok ? "text-emerald-300" : "bg-destructive/15 text-destructive")} title={s.problem ?? s.warning ?? "Repository code runs in locked-down Docker containers: no network, limited CPU / memory / time, read-only filesystem, no privileges."}>
      {ok ? <Lock className="size-3" /> : <AlertTriangle className="size-3" />}{s.mode === "docker" ? (ok ? "Docker sandbox" : "Sandbox unavailable") : "Host execution (unsafe)"}
    </span>
  );
}

function Bar({ v, className }: { v: number; className?: string }) {
  return <div className="h-1.5 w-full overflow-hidden rounded bg-muted"><div className={cn("h-full rounded", v >= 80 ? "bg-emerald-500" : v >= 60 ? "bg-amber-400" : "bg-red-500", className)} style={{ width: `${Math.max(2, Math.min(100, v))}%` }} /></div>;
}

function Finding({ f }: { f: QFinding }) {
  const open = useIde((s) => s.openFile);
  return (
    <button className="flex w-full items-start gap-2 border-b px-3 py-1.5 text-left hover:bg-accent/50" onClick={() => f.file && !f.file.startsWith("package-lock") && open(f.file, f.line || undefined)}>
      <Badge variant={SEV_BADGE[f.severity]} className="mt-0.5 w-14 justify-center">{f.severity}</Badge>
      <span className="min-w-0 flex-1">
        <span className="block text-[12px]">{f.message}{f.blocking && <Badge variant="destructive" className="ml-1.5">blocking</Badge>}</span>
        <span className="block truncate font-mono text-[11px] text-muted-foreground">{f.file}{f.line ? `:${f.line}` : ""} · {f.tool} {f.code}{f.cwe ? ` · ${f.cwe}` : ""}</span>
        {f.fix && <span className="block text-[11px] text-emerald-300">{f.fix}</span>}
      </span>
    </button>
  );
}

function FindingList({ title, icon, results, empty }: { title: string; icon: React.ReactNode; results: QAnalyzer[]; empty: string }) {
  const all = useMemo(() => results.flatMap((r) => r.findings).sort((a, b) => SEV_ORDER.indexOf(a.severity) - SEV_ORDER.indexOf(b.severity)), [results]);
  const [all_, setAll] = useState(false);
  const shown = all_ ? all : all.slice(0, 25);
  return (
    <section className="rounded-lg border">
      <header className="flex items-center gap-2 border-b px-3 py-2 font-semibold">{icon}{title}<span className="ml-auto flex gap-2 text-[11px] font-normal text-muted-foreground">{results.map((r) => <span key={r.tool} title={r.summary}>{r.tool}: {r.status === "ok" || r.status === "issues" ? `${r.findings.length}` : r.status}</span>)}</span></header>
      {all.length === 0 ? <div className="px-3 py-3 text-muted-foreground">{empty}</div> : shown.map((f, i) => <Finding key={i} f={f} />)}
      {all.length > 25 && <button className="w-full px-3 py-1.5 text-left text-[12px] text-primary hover:underline" onClick={() => setAll(!all_)}>{all_ ? "Show fewer" : `Show all ${all.length}`}</button>}
    </section>
  );
}

function Report({ r }: { r: QualityReport }) {
  const open = useIde((s) => s.openFile);
  const an = Object.values(r.analyzers);
  const by = (c: string) => an.filter((a) => a.category === c);
  const test = r.tests.find((t) => ["passed", "failed"].includes(t.status)) ?? r.tests[0];
  const sc = r.score;
  return (
    <div className="space-y-4 p-4">
      <section className="flex flex-wrap items-center gap-6 rounded-lg border p-4">
        <div className="text-center"><div className={cn("text-6xl font-bold leading-none", GRADE_COLOR[sc.grade])}>{sc.grade}</div><div className="mt-1 text-[11px] text-muted-foreground">{sc.overall ?? "–"} / 100</div></div>
        <div className="grid min-w-64 flex-1 gap-2">
          {Object.entries(sc.dimensions).map(([k, d]) => (
            <div key={k}><div className="flex justify-between text-[12px]"><span>{DIM_LABEL[k] ?? k} <span className="text-muted-foreground">· weight {d.weight}</span></span><span className="font-mono">{Math.round(d.score)}</span></div><Bar v={d.score} /><div className="text-[11px] text-muted-foreground">{d.detail}</div></div>
          ))}
          {sc.not_measured.length > 0 && <div className="text-[11px] text-muted-foreground">Not measured (left out of the score, not counted as a pass): {sc.not_measured.map((k) => DIM_LABEL[k] ?? k).join(", ")}</div>}
        </div>
      </section>

      <section className="rounded-lg border">
        <header className="flex items-center gap-2 border-b px-3 py-2 font-semibold"><FlaskConical className="size-4" />Tests<span className="ml-auto text-[11px] font-normal text-muted-foreground">{r.frameworks.join(" · ") || "no framework detected"}</span></header>
        {!test ? <div className="px-3 py-3 text-muted-foreground">No tests were run.</div> : (
          <div className="space-y-1.5 px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2"><Badge variant={test.status === "passed" ? "success" : test.status === "failed" ? "destructive" : "warning"}>{test.status.replace("_", " ")}</Badge><span>{test.summary}</span>{test.sandbox && <span className="text-[11px] text-muted-foreground">ran in {test.sandbox.mode}{test.sandbox.image ? ` (${test.sandbox.image})` : ""}</span>}</div>
            {(test.failed_tests ?? []).slice(0, 12).map((f) => <div key={f.id} className="truncate font-mono text-[11px] text-red-300" title={f.message}>✗ {f.id}{f.message ? ` — ${f.message}` : ""}</div>)}
            {test.status === "sandbox_unavailable" && <div className="text-[12px] text-amber-300">{test.summary}</div>}
          </div>
        )}
      </section>

      <section className="rounded-lg border">
        <header className="flex items-center gap-2 border-b px-3 py-2 font-semibold"><Gauge className="size-4" />Coverage{r.coverage && <span className="ml-auto font-mono text-[12px]">{r.coverage.percent}% of {r.coverage.total} lines · {r.coverage.tool}</span>}</header>
        {!r.coverage ? <div className="px-3 py-3 text-muted-foreground">Coverage was not collected (see notes below).</div> : r.coverage.files.slice(0, 20).map((f) => (
          <button key={f.path} className="grid w-full grid-cols-[minmax(0,1fr)_7rem_3rem] items-center gap-3 border-b px-3 py-1.5 text-left hover:bg-accent/50" onClick={() => open(f.path)} title={f.missing.length ? `Uncovered lines: ${f.missing.join(", ")}` : "fully covered"}>
            <span className="truncate font-mono text-[12px]">{f.path}<span className="ml-2 text-[11px] text-muted-foreground">{f.missing.slice(0, 3).join(", ")}</span></span><Bar v={f.percent} /><span className="text-right font-mono text-[12px]">{Math.round(f.percent)}%</span>
          </button>
        ))}
      </section>

      <FindingList title="Lint" icon={<Wrench className="size-4" />} results={by("lint")} empty="No lint findings." />
      <FindingList title="Type checking" icon={<Bug className="size-4" />} results={by("types")} empty="No type errors, or the type checker did not run." />
      <FindingList title="Security" icon={<ShieldAlert className="size-4" />} results={[...by("security"), ...by("dependency")]} empty="No security findings, or the scanners did not run." />

      {r.maintainability.available && r.maintainability.worst && r.maintainability.worst.length > 0 && (
        <section className="rounded-lg border">
          <header className="border-b px-3 py-2 font-semibold">Most complex functions <span className="text-[11px] font-normal text-muted-foreground">(average complexity {r.maintainability.avg_complexity})</span></header>
          {r.maintainability.worst.slice(0, 5).map((w) => <button key={`${w.file}:${w.line}`} className="flex w-full items-center gap-3 border-b px-3 py-1.5 text-left hover:bg-accent/50" onClick={() => open(w.file, w.line)}><span className="font-mono text-[12px]">{w.name}()</span><span className="truncate text-[11px] text-muted-foreground">{w.file}:{w.line}</span><span className="ml-auto text-[11px]">complexity {w.complexity} · {w.length} lines</span></button>)}
        </section>
      )}

      {r.notes.length > 0 && <section className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-[12px]"><div className="mb-1 font-semibold text-amber-200">Notes</div>{r.notes.map((n, i) => <div key={i} className="text-muted-foreground">• {n}</div>)}</section>}
      <div className="text-[11px] text-muted-foreground">Run {new Date(r.created * 1000).toLocaleString()} · {r.duration_s}s · {r.sandbox.mode === "docker" ? "every tool ran inside the Docker sandbox" : "executed on the host (SANDBOX_MODE=local)"}</div>
    </div>
  );
}

export function QualityTab({ repoId }: { repoId: string }) {
  const qc = useQueryClient();
  const info = useQuery({ queryKey: ["qinfo", repoId], queryFn: () => api.qualityInfo(repoId) });
  const latest = useQuery({ queryKey: ["qlatest", repoId], queryFn: () => api.qualityLatest(repoId) });
  const [jobId, setJobId] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [coverage, setCoverage] = useState(true);
  const job = useQuery({ queryKey: ["qjob", jobId], queryFn: () => api.qualityJob(jobId!), enabled: !!jobId, refetchInterval: (q) => (q.state.data?.status === "running" ? 1200 : false) });
  const start = useMutation({ mutationFn: () => api.qualityRun(repoId, chosen ?? undefined, coverage), onSuccess: (r) => setJobId(r.id), onError: (e: Error) => toast.error(e.message) });
  const running = start.isPending || job.data?.status === "running";
  useEffect(() => { if (job.data?.status === "done") { qc.invalidateQueries({ queryKey: ["qlatest", repoId] }); setJobId(null); toast.success(`Quality run finished: grade ${job.data.report?.score.grade}`); } if (job.data?.status === "error") toast.error(job.data.error ?? "Quality run failed"); }, [job.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const applicable = info.data?.analyzers.filter((a) => a.applies) ?? [];
  const selected = chosen ?? applicable.map((a) => a.name);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b px-3 py-2">
        <div className="font-semibold">Code quality</div><SandboxBadge />
        <details className="text-[12px]"><summary className="cursor-pointer text-muted-foreground">Tools ({selected.length} of {applicable.length})</summary>
          <div className="absolute z-10 mt-1 grid gap-1 rounded-md border bg-popover p-2 shadow-lg">
            {applicable.map((a) => <label key={a.name} className="flex items-center gap-2"><input type="checkbox" checked={selected.includes(a.name)} onChange={(e) => setChosen(e.target.checked ? [...selected, a.name] : selected.filter((x) => x !== a.name))} />{a.label}<span className="text-muted-foreground">{a.category}</span></label>)}
            <label className="mt-1 flex items-center gap-2 border-t pt-1"><input type="checkbox" checked={coverage} onChange={(e) => setCoverage(e.target.checked)} />Collect coverage</label>
          </div></details>
        <Button size="sm" className="ml-auto" disabled={running} onClick={() => start.mutate()}>{running ? <Loader2 className="animate-spin" /> : <Play />}{running ? "Running…" : "Run analysis"}</Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {running && <div className="space-y-1 border-b bg-muted/30 px-4 py-3 text-[12px]">{(job.data?.progress ?? []).map((p, i, a) => <div key={i} className={i === a.length - 1 ? "text-foreground" : "text-muted-foreground"}>{i === a.length - 1 ? <Loader2 className="mr-1.5 inline size-3 animate-spin" /> : "✓ "}{p.message}</div>)}{!job.data?.progress.length && <div>Starting…</div>}</div>}
        {latest.data ? <Report r={latest.data} /> : !running && <div className="flex flex-col items-center gap-2 p-10 text-center text-muted-foreground"><ShieldCheck className="size-8" /><div>No analysis yet. Run one to see test results, coverage, lint, type, security and dependency findings and a quality score.</div><div className="text-[11px]">Tools: {info.data?.analyzers.map((a) => a.label).join(", ")} · Frameworks: {info.data?.frameworks.join(", ") || "none detected"}</div></div>}
      </ScrollArea>
    </div>
  );
}
