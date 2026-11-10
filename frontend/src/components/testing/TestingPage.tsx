"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleDashed, CircleX, ChevronDown, FlaskConical, Play, ShieldAlert, ShieldCheck, SkipForward, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn, fmtMs } from "@/lib/utils";
import type { RecordedRun, TestDiscovery, TestFailure, TestRun } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { PageHeader, Segmented, Stat } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { CopyButton, FileLink, StatusDot } from "@/components/common/bits";
import { ago } from "@/components/shell/IndexStatus";

const OUT_TONE = { passed: "success", failed: "destructive", error: "destructive", skipped: "secondary", xfail: "secondary", xpass: "warning", "not run": "outline" } as const;

function ExecBanner({ d }: { d: TestDiscovery }) {
  const s = d.sandbox;
  const real = d.can_execute;
  if (!d.framework && d.file_count === 0) {
    return (
      <div className="flex items-start gap-2.5 rounded-xl border bg-secondary/40 px-3.5 py-3 text-xs">
        <FlaskConical className="mt-0.5 size-4 text-muted-foreground" />
        <div className="min-w-0"><div className="text-[13px] font-medium">This project has no tests yet</div>
          <div className="mt-0.5 leading-relaxed text-muted-foreground">No test files and no test framework were found, so there is nothing to run. That is not an error. To add some: Python → <code className="font-mono">pip install pytest</code> and create <code className="font-mono">tests/test_*.py</code>; React/Vite → <code className="font-mono">npm i -D vitest</code> and create <code className="font-mono">*.test.jsx</code> files. Then import the project again. The AI chat in <b>Test</b> mode can write them for you.</div></div>
      </div>
    );
  }
  const tone = real ? (s.isolated ? "border-success/30 bg-success/8" : "border-warning/40 bg-warning/10") : "border-destructive/30 bg-destructive/6";
  return (
    <div className={cn("flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-xs", tone)}>
      {real ? (s.isolated ? <ShieldCheck className="mt-0.5 size-4 text-success" /> : <ShieldAlert className="mt-0.5 size-4 text-warning" />) : <CircleX className="mt-0.5 size-4 text-destructive" />}
      <div className="min-w-0"><div className="text-[13px] font-medium">{real ? (s.isolated ? "Real execution · isolated Docker sandbox" : "Real execution · local mode, NOT isolated") : "Tests can’t be executed here"}</div>
        <div className="text-muted-foreground">{real ? (s.isolated ? "Your tests run for real in a locked-down container (no network, read-only filesystem)." : s.warning ?? "Repository code runs directly on this machine.") : d.note ?? s.problem ?? "No test framework was detected, or the sandbox is unavailable. Nothing is run and no results are invented."}</div></div>
    </div>
  );
}

function outcomeOf(run: TestRun | undefined, file: string, name: string): keyof typeof OUT_TONE {
  if (!run?.executed || !run.tests) return "not run";
  const hit = run.tests.find((t) => t.id.startsWith(file + "::") && (t.id.endsWith("::" + name) || t.id.split("::").pop()!.startsWith(name + "[")));
  return hit ? hit.outcome : "not run";
}

function Failure({ f, open: o }: { f: TestFailure; open?: boolean }) {
  const [open, setOpen] = useState(!!o);
  return (
    <div className="rounded-lg border border-destructive/25 bg-destructive/5">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-start gap-2 px-3 py-2 text-left">
        <CircleX className="mt-0.5 size-4 shrink-0 text-destructive" />
        <span className="min-w-0 flex-1"><span className="block break-all font-mono text-xs font-medium">{f.id}</span><span className="mt-0.5 block break-words text-xs text-muted-foreground">{f.error ?? f.message}</span></span>
        {f.location && <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{f.location.file}:{f.location.line}</span>}
        <ChevronDown className={cn("mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-2 border-t px-3 py-2.5">
          {f.frames && f.frames.length > 0 && <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Where it failed (innermost last)</div><ol className="space-y-0.5">{f.frames.map((fr, i) => <li key={i} className="flex items-center gap-1.5 text-xs"><span className="w-4 text-right text-muted-foreground">{i + 1}</span><FileLink path={fr.file} line={fr.line} /><span className="text-muted-foreground">in {fr.func}</span></li>)}</ol></div>}
          {f.traceback ? <pre className="max-h-72 overflow-auto rounded-md bg-surface p-2.5 font-mono text-[11.5px] leading-relaxed">{f.traceback}</pre> : <p className="text-xs text-muted-foreground">This test runner did not provide a traceback. See the full output.</p>}
        </div>
      )}
    </div>
  );
}

function RunView({ rec, disc }: { rec: RecordedRun; disc?: TestDiscovery }) {
  const run = rec.run;
  const [filter, setFilter] = useState<"all" | "failed" | "passed" | "skipped">("all");
  const [tab, setTab] = useState<"output" | "stderr">("output");
  const c = run.counts ?? {};
  const executedIds = run.tests ?? [];
  const shown = executedIds.filter((t) => filter === "all" || (filter === "failed" ? t.outcome === "failed" || t.outcome === "error" : filter === "skipped" ? t.outcome === "skipped" || t.outcome === "xfail" : t.outcome === "passed"));
  const failed = run.failed_tests ?? [];
  const stoppedEarly = (c.failed ?? 0) >= 10 && run.framework === "pytest";
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={`Executed ${ago(rec.recorded_at)}`} description={`${run.framework ?? "tests"} · ${run.sandbox?.mode === "docker" ? "isolated Docker sandbox" : "local mode (not isolated)"} · exit code ${run.exit_code ?? "–"}${rec.targets.length ? ` · ${rec.targets.length} target(s)` : " · whole suite"}`}
          actions={<Badge variant={run.passed ? "success" : run.status === "failed" ? "destructive" : "warning"} className="capitalize">{run.status.replace(/_/g, " ")}</Badge>} />
        <CardBody className="space-y-4">
          <div className="flex items-start gap-2 rounded-lg bg-surface px-3 py-2"><span className="mt-0.5 shrink-0 text-muted-foreground">$</span><code className="min-w-0 flex-1 break-all font-mono text-[12px]">{run.command}</code><CopyButton text={run.command ?? ""} label="Copy" /></div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            <Stat label="Executed" value={run.total ?? executedIds.length} hint={disc ? `of ${disc.case_count} discovered` : undefined} />
            <Stat label="Passed" value={c.passed ?? 0} tone={c.passed ? "success" : undefined} />
            <Stat label="Failed" value={c.failed ?? 0} tone={c.failed ? "destructive" : undefined} />
            <Stat label="Skipped" value={(c.skipped ?? 0) + (c.xfailed ?? 0)} />
            <Stat label="Errors" value={c.error ?? 0} tone={c.error ? "destructive" : undefined} hint={run.duration_ms != null ? fmtMs(run.duration_ms) : undefined} />
          </div>
          <p className="text-xs text-muted-foreground">{run.summary}</p>
          {stoppedEarly && <div className="flex items-center gap-2 rounded-md bg-warning/10 px-2.5 py-1.5 text-xs text-warning"><TriangleAlert className="size-3.5" />pytest stops after 10 failures (--maxfail=10), so some tests may not have run.</div>}
          {run.truncated && <div className="text-xs text-warning">The output was longer than what is kept; the end of it is shown.</div>}
        </CardBody>
      </Card>

      {failed.length > 0 && <div className="space-y-2"><h3 className="text-[13px] font-semibold">Failures ({failed.length})</h3>{failed.map((f, i) => <Failure key={f.id} f={f} open={i === 0} />)}</div>}

      {executedIds.length > 0 && (
        <Card>
          <CardHeader title="Every test that ran" description="Parsed from the runner’s own output" actions={<Segmented size="sm" value={filter} onChange={setFilter} options={[{ value: "all", label: `All ${executedIds.length}` }, { value: "passed", label: "Passed" }, { value: "failed", label: "Failed" }, { value: "skipped", label: "Skipped" }]} />} />
          <CardBody className="max-h-80 overflow-y-auto p-0"><ul className="divide-y">
            {shown.map((t) => <li key={t.id} className="flex items-center gap-2.5 px-4 py-1.5 text-xs"><Badge variant={OUT_TONE[t.outcome]} className="w-16 justify-center capitalize">{t.outcome}</Badge><span className="min-w-0 flex-1 truncate font-mono" title={t.id}>{t.id}</span>{run.skipped_reasons && t.outcome === "skipped" && <span className="hidden text-muted-foreground sm:inline" />}</li>)}
          </ul></CardBody>
        </Card>
      )}
      {run.skipped_reasons && Object.keys(run.skipped_reasons).length > 0 && <Card><CardHeader title="Skipped" /><CardBody><ul className="space-y-1 text-xs">{Object.entries(run.skipped_reasons).map(([k, v]) => <li key={k}><span className="font-mono">{k}</span> <span className="text-muted-foreground">{v}</span></li>)}</ul></CardBody></Card>}

      <Card>
        <CardHeader title="Raw output" description="Exactly what the process printed" actions={<><Segmented size="sm" value={tab} onChange={setTab} options={[{ value: "output", label: "stdout + stderr" }, { value: "stderr", label: "stderr only" }]} /><CopyButton text={tab === "output" ? run.output : run.stderr ?? ""} label="Copy" /></>} />
        <CardBody>{(tab === "output" ? run.output : run.stderr) ? <pre className="max-h-[28rem] overflow-auto rounded-lg bg-surface p-3 font-mono text-[11.5px] leading-relaxed">{tab === "output" ? run.output : run.stderr}</pre> : <p className="text-xs text-muted-foreground">Nothing was printed to {tab === "stderr" ? "stderr" : "the console"}.</p>}</CardBody>
      </Card>
    </div>
  );
}

export function TestingPage({ repoId }: { repoId: string }) {
  const qc = useQueryClient();
  const disc = useQuery({ queryKey: ["test-discovery", repoId], queryFn: () => api.testDiscovery(repoId), retry: false });
  const runs = useQuery({ queryKey: ["test-runs", repoId], queryFn: () => api.testRuns(repoId, 20, true), retry: false });
  const [pick, setPick] = useState<string | null>(null);
  const [expand, setExpand] = useState<Set<string>>(new Set());
  const [notExecuted, setNotExecuted] = useState<TestRun | null>(null);
  const run = useMutation({
    mutationFn: (targets?: string[]) => api.runTests(repoId, targets),
    onSuccess: (r) => {
      if (r.executed) { setNotExecuted(null); setPick(null); qc.invalidateQueries({ queryKey: ["test-runs", repoId] }); toast[r.passed ? "success" : "warning"](r.summary); }
      else { setNotExecuted(r); toast.error(`Not executed: ${r.summary}`); }
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const auto = useRef(false);
  useEffect(() => { if (new URLSearchParams(window.location.search).get("run") === "1" && !auto.current && disc.data?.can_execute) { auto.current = true; run.mutate(undefined); } }, [disc.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const list = runs.data ?? [];
  const current = list.find((r) => r.id === pick) ?? list[0];
  const d = disc.data;
  const covered = useMemo(() => new Set((d?.files ?? []).flatMap((f) => f.covers_verified)), [d]);

  return (
    <div className="mx-auto max-w-[1100px] space-y-5 p-4 sm:p-6">
      <PageHeader title="Testing" description="What tests exist (parsed from your code), and what actually happened when they were run. Every result below is the real output of a real process; if nothing ran, this page says so." icon={<FlaskConical />}
        actions={<Button onClick={() => run.mutate(undefined)} loading={run.isPending} disabled={!!d && !d.can_execute}><Play />Run all tests</Button>} />
      {disc.isLoading ? <Skeleton className="h-16" /> : disc.isError ? <ErrorState title="Couldn’t inspect the project’s tests" error={disc.error} onRetry={() => disc.refetch()} /> : d && <ExecBanner d={d} />}

      {d && (
        <Card>
          <CardHeader title="Discovered tests" description="Parsed from source. Nothing has been executed by this section." icon={<CircleDashed className="size-4" />}
            actions={d.framework ? <Badge variant="secondary">{d.framework}</Badge> : <Badge variant="warning">no framework detected</Badge>} />
          <CardBody className="space-y-3">
            {d.command && <div className="flex items-center gap-2 text-xs text-muted-foreground"><span>Would run:</span><code className="min-w-0 flex-1 truncate rounded bg-surface px-2 py-1 font-mono text-[11.5px]">{d.command}</code></div>}
            <div className="flex gap-6 text-xs"><span><b className="tabular-nums text-sm">{d.file_count}</b> test files</span><span><b className="tabular-nums text-sm">{d.case_count}</b> test cases</span><span><b className="tabular-nums text-sm">{covered.size}</b> source modules imported by tests</span></div>
            {d.files.length === 0 ? <EmptyState className="py-6" icon={<FlaskConical className="size-5" />} title="No tests found in this project" description="The parser found no test files or test functions. Tests need to exist before they can be run." />
              : <ul className="divide-y rounded-lg border">{d.files.map((f) => {
                const open = expand.has(f.file);
                return (
                  <li key={f.file}>
                    <div className="flex items-center gap-2 px-3 py-2"><button aria-expanded={open} aria-label={`Toggle ${f.file}`} onClick={() => setExpand((s) => { const n = new Set(s); if (n.has(f.file)) n.delete(f.file); else n.add(f.file); return n; })}><ChevronDown className={cn("size-4 text-muted-foreground transition-transform", !open && "-rotate-90")} /></button>
                      <FileLink path={f.file} /><Badge variant="outline">{f.cases.length} case{f.cases.length === 1 ? "" : "s"}</Badge>
                      <span className="ml-auto flex items-center gap-1.5"><Button size="xs" variant="outline" disabled={!d.can_execute || run.isPending} onClick={() => run.mutate([f.file])}><Play />Run this file</Button></span></div>
                    {open && <div className="space-y-1.5 border-t bg-surface/40 px-4 py-2.5 text-xs">
                      {(f.covers_verified.length > 0 || f.covers_inferred.length > 0) && <div className="flex flex-wrap items-center gap-1.5"><span className="text-muted-foreground">Covers:</span>{f.covers_verified.map((m) => <Badge key={m} variant="success" title="The test file imports this module">{m}</Badge>)}{f.covers_inferred.map((m) => <Badge key={m} variant="warning" title="Matched by file name only">{m} (inferred)</Badge>)}</div>}
                      <ul className="space-y-0.5">{f.cases.map((cs) => { const o = outcomeOf(current?.run, f.file, cs.name); return <li key={cs.name + cs.line} className="flex items-center gap-2"><Badge variant={OUT_TONE[o]} className="w-16 justify-center capitalize">{o === "not run" ? "not run" : o}</Badge><span className="font-mono">{cs.name}</span><span className="ml-auto text-muted-foreground">line {cs.line}</span></li>; })}</ul>
                      {current && <p className="text-[11px] text-muted-foreground">Outcome column reflects the selected recorded run below; “not run” means that run did not execute this test.</p>}
                    </div>}
                  </li>);
              })}</ul>}
          </CardBody>
        </Card>
      )}

      {run.isPending && <Card><CardBody className="space-y-3" role="status" aria-live="polite"><div className="flex items-center gap-2 text-[13px]"><StatusDot tone="running" />Running {d?.command ?? "tests"}…</div><Skeleton className="h-20" /></CardBody></Card>}

      {notExecuted && (
        <Card className="border border-destructive/30"><CardBody className="space-y-2">
          <div className="flex items-center gap-2 text-[13px] font-semibold text-destructive"><CircleX className="size-4" />Not executed</div>
          <p className="text-xs text-muted-foreground">{notExecuted.summary}</p>
          <p className="text-xs text-muted-foreground">No tests ran, so there are no results, counts or history for this attempt.</p>
          {notExecuted.output && <pre className="max-h-48 overflow-auto rounded-md bg-surface p-2 font-mono text-[11px]">{notExecuted.output}</pre>}
        </CardBody></Card>
      )}

      <div>
        <div className="mb-2 flex items-center justify-between gap-3"><h2 className="text-[13px] font-semibold">Execution results</h2>
          {list.length > 1 && <div className="flex flex-wrap items-center gap-1.5 text-xs"><span className="text-muted-foreground">Recorded runs:</span>{list.slice(0, 6).map((r) => <button key={r.id} onClick={() => setPick(r.id)} aria-pressed={current?.id === r.id} className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5", current?.id === r.id ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/60")}><StatusDot tone={r.run.passed ? "success" : r.run.status === "failed" ? "destructive" : "warning"} />{ago(r.recorded_at)}<span className="tabular-nums">{r.run.counts?.passed ?? 0}✓ {r.run.counts?.failed ?? 0}✗</span></button>)}</div>}</div>
        {runs.isLoading ? <Skeleton className="h-40" /> : !current ? <EmptyState icon={<CircleDashed className="size-5" />} title="Not executed yet" description={d?.can_execute ? "Nothing has been run for this project. Run the tests to see real results here." : "Nothing has been run, and the tests can’t be executed in this environment right now (see above)."} action={d?.can_execute ? <Button onClick={() => run.mutate(undefined)} loading={run.isPending}><Play />Run all tests</Button> : undefined} />
          : <RunView key={current.id} rec={current} disc={d} />}
      </div>
    </div>
  );
}
