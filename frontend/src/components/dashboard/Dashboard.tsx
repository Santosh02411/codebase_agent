"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Activity as ActivityIcon, AlertTriangle, ArrowRight, CircleCheck, Box, CircleHelp, FlaskConical, Loader2, MessagesSquare, RefreshCw, ScanSearch, Sparkles, TriangleAlert, Waypoints } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useActiveIndexing, useHealth, useStats } from "@/hooks/queries";
import { useAgentRun } from "@/hooks/useAgentRun";
import { useOpenFile } from "@/hooks/useOpen";
import { useIde } from "@/store/ide";
import { force } from "@/lib/graphLayout";
import { cn, fmtMs, parseLines } from "@/lib/utils";
import type { GraphNode, Insights, Mode, OverviewData, RepoStats } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Progress } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { FileLink, SeverityBadge, StatusDot, nf } from "@/components/common/bits";
import { Markdown } from "@/components/common/Markdown";
import type { StaticReview } from "@/lib/types";
import { clusterKeys, clusterColor } from "@/components/arch3d/layout3d";
import { ago } from "@/components/shell/IndexStatus";

const Tile = ({ i = 0, className, children }: { i?: number; className?: string; children: React.ReactNode }) => (
  <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i, duration: 0.25 }} className={className}>{children}</motion.div>
);

/** What the parser found, as sentences. No model involved, and labelled as such. */
function DetectedFacts({ ins, stats }: { ins: Insights; stats?: RepoStats }) {
  const items: string[] = [];
  const langs = ins.languages.map((l) => l.language).slice(0, 3).join(", ");
  if (stats) items.push(`${nf(stats.files)} files and ${nf(stats.lines)} lines of code${langs ? `, mostly ${langs}` : ""}.`);
  if (ins.entry_points.length) items.push(`Entry points: ${ins.entry_points.slice(0, 4).map((e) => `${e.file} (${e.reason})`).join("; ")}.`);
  if (ins.routes.length) items.push(`${ins.routes.length} API route${ins.routes.length === 1 ? "" : "s"}, for example ${ins.routes.slice(0, 3).map((r) => `${r.method} ${r.path}`).join(", ")}.`);
  if (ins.folders.length) items.push(`Main folders: ${ins.folders.slice(0, 5).map((f) => `${f.path}/ (${f.files} files)`).join(", ")}.`);
  if (ins.key_modules.length) items.push(`Most-imported modules: ${ins.key_modules.slice(0, 4).map((m) => `${m.file} (used by ${m.imported_by})`).join(", ")}.`);
  if (ins.hubs.length) items.push(`Most-called functions: ${ins.hubs.slice(0, 3).map((h) => `${h.qualname} (${h.callers} callers)`).join(", ")}.`);
  if (ins.external.length) items.push(`External packages: ${ins.external.slice(0, 8).map((e) => e.name).join(", ")}.`);
  return <ul className="space-y-1.5 text-[13px] leading-relaxed">{items.map((t, i) => <li key={i} className="flex gap-2"><span className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground/60" />{t}</li>)}</ul>;
}

function Understanding({ repoId, ins, stats }: { repoId: string; ins?: Insights; stats?: RepoStats }) {
  const qc = useQueryClient();
  const openFile = useOpenFile();
  const [full, setFull] = useState(false);
  const ov = useQuery({ queryKey: ["overview", repoId], queryFn: () => api.overview(repoId) });
  const gen = useMutation({
    mutationFn: (force: boolean) => api.makeOverview(repoId, force),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["overview", repoId] }); if (r.state === "unavailable") toast.message("AI explanation needs a model", { description: r.reason }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const o: OverviewData | null | undefined = ov.data?.overview;
  const mock = ov.data?.llm_mock;
  const onCite = (n: number) => { const s = o?.sources?.find((x) => x.cite === n); if (s) openFile(s.file, parseLines(s.lines)[0], parseLines(s.lines)[1]); };
  return (
    <Card className="relative overflow-hidden">
      <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full bg-primary/10 blur-3xl" />
      <CardHeader icon={<Sparkles className="size-4 text-primary" />} title="What this project does and how it works" description={o ? `AI explanation · ${o.llm ?? "model"} · ${ago(o.created)} · grounded in ${o.sources?.length ?? 0} retrieved code snippets` : "AI project understanding"}
        actions={o ? <Button size="xs" variant="ghost" loading={gen.isPending} onClick={() => gen.mutate(true)}><RefreshCw />Regenerate</Button> : undefined} />
      <CardBody className="space-y-3">
        {ov.isLoading ? <div className="space-y-2"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-2/3" /></div>
          : ov.isError ? <ErrorState error={ov.error} onRetry={() => ov.refetch()} />
          : o ? (
            <>
              {ov.data?.stale && <div className="flex items-center gap-2 rounded-md bg-warning/10 px-2.5 py-1.5 text-xs text-warning"><TriangleAlert className="size-3.5" />The project was re-indexed after this was written. It may be out of date.</div>}
              {o.llm?.startsWith("mock") && <div className="rounded-md bg-warning/10 px-2.5 py-1.5 text-xs text-warning">This text came from the offline mock model, not from AI reasoning.</div>}
              <div className={cn("relative", !full && "max-h-72 overflow-hidden")}><Markdown sources={o.sources} onCite={onCite}>{o.answer}</Markdown>{!full && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-panel to-transparent" />}</div>
              <div className="flex items-center gap-2"><Button size="xs" variant="outline" onClick={() => setFull(!full)}>{full ? "Show less" : "Read the full explanation"}</Button><span className="text-[11px] text-muted-foreground">Numbered citations open the exact code.</span></div>
            </>
          ) : gen.isPending ? (
            <div className="space-y-3" role="status" aria-live="polite"><div className="flex items-center gap-2 text-[13px]"><Loader2 className="size-4 animate-spin text-primary" />Reading the code, following the flows and writing the explanation. This can take up to a minute.</div><Skeleton className="h-4 w-4/5" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-3/5" /></div>
          ) : mock ? (
            <div className="space-y-3">
              <div className="flex items-start gap-2.5 rounded-lg border border-warning/30 bg-warning/8 px-3 py-2.5 text-xs"><CircleHelp className="mt-0.5 size-4 shrink-0 text-warning" /><div><div className="text-[13px] font-medium">Offline mode: no AI model is configured</div><p className="mt-0.5 text-muted-foreground">AI project understanding needs a model, so none is generated here and nothing is faked. Add a key (see <code className="font-mono">docs/ENV_SETUP.md</code>) and this card will write a cited explanation of the project. What follows was detected from your code by the parser, with no AI.</p></div></div>
              {ins ? <DetectedFacts ins={ins} stats={stats} /> : <Skeleton className="h-24" />}
            </div>
          ) : (
            <div className="space-y-3">
              {ins ? <DetectedFacts ins={ins} stats={stats} /> : <Skeleton className="h-24" />}
              <div className="flex flex-wrap items-center gap-3 rounded-lg bg-surface px-3 py-2.5"><div className="min-w-0 flex-1 text-xs text-muted-foreground">The facts above are detected from the code. Generate an AI explanation of what the project does and how the pieces fit together, with citations to the code it read. It runs the agent once and is saved for this version of the project.</div><Button onClick={() => gen.mutate(false)}><Sparkles />Generate AI project understanding</Button></div>
            </div>
          )}
      </CardBody>
    </Card>
  );
}

/** The product's main feature, first on the page: a live strict review of the whole project (about a second, no AI model needed). */
function ReviewCard({ repoId }: { repoId: string }) {
  const q = useQuery({ queryKey: ["static-review", repoId], queryFn: () => api.reviewStatic(repoId), staleTime: 30_000 });
  const r: StaticReview | undefined = q.data;
  const status = useQuery({ queryKey: ["source-status", repoId], queryFn: () => api.sourceStatus(repoId), retry: false, staleTime: 30_000 });
  const changed = status.data?.count ?? 0;
  const high = r?.summary.by_severity.high ?? 0, med = r?.summary.by_severity.medium ?? 0, low = r?.summary.by_severity.low ?? 0;
  const top = (r?.findings ?? []).filter((f) => f.severity === "high").slice(0, 4);
  return (
    <Card className="relative overflow-hidden border border-primary/25">
      <div aria-hidden className="pointer-events-none absolute -left-20 -top-20 size-64 rounded-full bg-primary/10 blur-3xl" />
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-start gap-4">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground"><ScanSearch className="size-5" /></span>
            <div className="min-w-0"><h2 className="text-base font-semibold">Automated code review</h2>
              <p className="mt-0.5 text-[13px] text-muted-foreground">Every file is checked for syntax errors, typos and undefined names, wrong imports and call arguments, bugs and security problems. Real parsers and fixed rules, no guessing.</p></div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2"><Button asChild size="lg"><Link href="/review"><ScanSearch />Review code</Link></Button><Button asChild size="lg" variant="outline"><Link href="/review?tab=paste">Paste code to review</Link></Button></div>
        </div>
        {changed > 0 && <p className="rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">{changed} file{changed === 1 ? "" : "s"} changed in your original folder since import. Sync before reviewing to include them (Code Review page → Sync & review again).</p>}
        {q.isLoading ? <div className="space-y-2" role="status"><Skeleton className="h-5 w-64" /><Skeleton className="h-16" /></div>
          : q.isError ? <p className="text-xs text-destructive">The review could not run: {(q.error as Error).message}</p>
          : r && (
            <div className="space-y-3">
              <div className={cn("flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg px-3 py-2.5", high + med ? "bg-destructive/8" : "bg-success/8")}>
                {high + med ? <AlertTriangle className="size-5 text-destructive" /> : <CircleCheck className="size-5 text-success" />}
                <div className="text-[13px] font-semibold">{high + med ? `${high + med} problem${high + med === 1 ? "" : "s"} that can crash or misbehave` : `No errors found in ${r.coverage.files_analysed} files`}</div>
                <div className="flex gap-4 text-xs text-muted-foreground"><span><b className="text-sm tabular-nums text-destructive">{high}</b> high</span><span><b className="text-sm tabular-nums text-warning">{med}</b> medium</span><span><b className="text-sm tabular-nums text-foreground">{low}</b> low</span><span>{r.coverage.files_analysed} files · {r.duration_ms} ms</span></div>
              </div>
              {top.length > 0 && <ul className="space-y-1.5">{top.map((f) => <li key={f.id} className="flex items-start gap-2.5 rounded-lg bg-surface/60 px-3 py-2 text-xs"><SeverityBadge s={f.severity} /><span className="min-w-0 flex-1"><FileLink path={f.file} line={f.line} /><span className="block text-muted-foreground">{f.message}</span></span><Badge variant="outline" className="hidden font-mono sm:inline-flex">{f.rule}</Badge></li>)}</ul>}
              {top.length > 0 && r.summary.total > top.length && <Link href="/review" className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">See all {r.summary.total} findings with code and fixes <ArrowRight className="size-3.5" /></Link>}
            </div>
          )}
      </CardBody>
    </Card>
  );
}

function StartHere({ ins }: { ins?: Insights }) {
  const { run } = useAgentRun();
  const router = useRouter();
  const go = (mode: Mode, q: string) => { router.push("/chat"); void run(mode, q); };
  return (
    <Card className="h-full">
      <CardHeader title="Where to start" description="Questions built from this project’s own routes, functions and gaps" icon={<MessagesSquare className="size-4" />} />
      <CardBody className="space-y-2">
        {!ins ? <Skeleton className="h-40" /> : ins.suggested_questions.length === 0 ? <p className="text-xs text-muted-foreground">Not enough structure was found to suggest specific questions yet. Ask anything in the chat.</p> : ins.suggested_questions.map((s) => (
          <button key={s.question} onClick={() => go(s.mode, s.question)} className="group w-full rounded-lg border bg-panel px-3 py-2 text-left transition-all hover:border-primary/40 hover:bg-primary/5">
            <div className="flex items-start gap-2"><span className="min-w-0 flex-1 text-[13px]">{s.question}</span><ArrowRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" /></div>
            <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground"><Badge variant="secondary" className="capitalize">{s.mode === "review" ? "review" : "explain"}</Badge>{s.basis}</div>
          </button>
        ))}
        <Button asChild size="sm" variant="ghost" className="w-full justify-start"><Link href="/chat"><MessagesSquare />Ask your own question</Link></Button>
      </CardBody>
    </Card>
  );
}

function Constellation({ repoId }: { repoId: string }) {
  const router = useRouter();
  const q = useQuery({ queryKey: ["system-graph", repoId], queryFn: () => api.graphSystem(repoId, 0) });
  const m = useMemo(() => {
    const g = q.data; if (!g || !g.files.length) return null;
    const ck = clusterKeys(g.files); const counts = new Map<string, number>(); ck.forEach((c) => counts.set(c, (counts.get(c) ?? 0) + 1));
    const w = new Map<string, number>();
    for (const e of g.edges) { if (e.type === "call" || e.type === "inherit") continue; const a = ck.get(e.source), b = ck.get(e.target); if (!a || !b || a === b) continue; const k = a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`; w.set(k, (w.get(k) ?? 0) + 1); }
    const nodes = [...counts].map(([id, n]) => ({ id, name: id, file: id, kind: "directory", count: n } as GraphNode));
    const edges = [...w].map(([k, v]) => { const [source, target] = k.split("\u0000"); return { source, target, weight: v } as never; });
    const pos = force(nodes, edges);
    const xs = [...pos.values()].map((p) => p.x), ys = [...pos.values()].map((p) => p.y);
    const x0 = Math.min(...xs) - 60, x1 = Math.max(...xs) + 120, y0 = Math.min(...ys) - 40, y1 = Math.max(...ys) + 40;
    return { nodes, links: [...w].map(([k, v]) => { const [a, b] = k.split("\u0000"); return { a, b, v }; }), pos, box: [x0, y0, x1 - x0, y1 - y0] as const };
  }, [q.data]);
  if (q.isLoading) return <Skeleton className="h-56" />;
  if (!m) return <p className="py-10 text-center text-xs text-muted-foreground">No structure to draw yet.</p>;
  return (
    <div className="relative">
      <svg viewBox={m.box.join(" ")} className="h-56 w-full" role="img" aria-label="Folders of the project linked by imports">
        {m.links.map((l, i) => { const a = m.pos.get(l.a)!, b = m.pos.get(l.b)!; return <line key={i} x1={a.x + a.w / 2} y1={a.y + a.h / 2} x2={b.x + b.w / 2} y2={b.y + b.h / 2} stroke="hsl(var(--muted-foreground))" strokeOpacity={Math.min(0.7, 0.18 + l.v * 0.08)} strokeWidth={Math.min(4, 1 + l.v * 0.3)} />; })}
        {m.nodes.map((n, i) => { const p = m.pos.get(n.id)!; const r = 7 + Math.sqrt(n.count ?? 1) * 3.2; return (
          <g key={n.id} transform={`translate(${p.x + p.w / 2},${p.y + p.h / 2})`} className="cursor-pointer" onClick={() => router.push("/architecture")}>
            <circle r={r} fill={clusterColor(i)} fillOpacity={0.85}><title>{n.id}: {n.count} files</title></circle>
            <text y={r + 13} textAnchor="middle" className="fill-foreground text-[11px]" style={{ paintOrder: "stroke", stroke: "hsl(var(--panel))", strokeWidth: 3 }}>{n.id.length > 18 ? "…" + n.id.slice(-17) : n.id}</text>
          </g>); })}
      </svg>
    </div>
  );
}

function ArchitectureGlance({ repoId, ins }: { repoId: string; ins?: Insights }) {
  return (
    <Card className="h-full">
      <CardHeader title="Architecture at a glance" description="Folders linked by the imports between them (from the parsed code)" icon={<Box className="size-4" />} actions={<Button asChild size="xs"><Link href="/architecture?p=system"><Box />Open 3D explorer</Link></Button>} />
      <CardBody className="space-y-4">
        <Constellation repoId={repoId} />
        {ins && (
          <div className="grid gap-4 sm:grid-cols-2">
            <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Entry points</div>{ins.entry_points.length === 0 ? <p className="text-xs text-muted-foreground">None detected by route or conventional name.</p> : <ul className="space-y-1">{ins.entry_points.slice(0, 4).map((e) => <li key={e.file} className="text-xs"><FileLink path={e.file} /><span className="block pl-1 text-[11px] text-muted-foreground">{e.detail || e.reason}</span></li>)}</ul>}</div>
            <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Key modules (most imported)</div>{ins.key_modules.length === 0 ? <p className="text-xs text-muted-foreground">No cross-file imports resolved.</p> : <ul className="space-y-1">{ins.key_modules.slice(0, 4).map((m) => <li key={m.file} className="flex items-center gap-2 text-xs"><FileLink path={m.file} /><Badge variant="outline" className="ml-auto">{m.imported_by}×</Badge></li>)}</ul>}</div>
            <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Hub functions (most called)</div>{ins.hubs.length === 0 ? <p className="text-xs text-muted-foreground">No resolved calls between functions.</p> : <ul className="space-y-1">{ins.hubs.slice(0, 4).map((h) => <li key={h.id} className="flex items-center gap-2 text-xs"><FileLink path={h.file} line={h.line}>{h.qualname}</FileLink><Badge variant="outline" className="ml-auto">{h.callers} callers</Badge></li>)}</ul>}</div>
            <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">External packages</div>{ins.external.length === 0 ? <p className="text-xs text-muted-foreground">None imported.</p> : <div className="flex flex-wrap gap-1.5">{ins.external.slice(0, 10).map((e) => <Badge key={e.name} variant="secondary" title={`imported in ${e.files} files`}>{e.name}</Badge>)}</div>}</div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function Risks({ repoId, ins }: { repoId: string; ins?: Insights }) {
  const runs = useQuery({ queryKey: ["test-runs", repoId, "latest"], queryFn: () => api.testRuns(repoId, 1, false), retry: false });
  const quality = useQuery({ queryKey: ["quality-latest", repoId], queryFn: () => api.qualityLatest(repoId), retry: false });
  const last = runs.data?.[0]?.run;
  const high = quality.data ? Object.values(quality.data.analyzers).flatMap((a) => a.findings).filter((f) => f.severity === "critical" || f.severity === "high") : [];
  const Row = ({ tone, title, children }: { tone: "bad" | "warn" | "ok" | "idle"; title: string; children?: React.ReactNode }) => (
    <li className="flex gap-2.5"><StatusDot tone={tone === "bad" ? "destructive" : tone === "warn" ? "warning" : tone === "ok" ? "success" : "muted"} /><div className="min-w-0 flex-1 text-[13px]"><div className="font-medium">{title}</div>{children && <div className="mt-0.5 text-xs text-muted-foreground">{children}</div>}</div></li>
  );
  return (
    <Card className="h-full">
      <CardHeader title="Risks and findings" description="Facts from the parser, the test runner and the last quality scan" icon={<TriangleAlert className="size-4" />} />
      <CardBody>
        <ul className="space-y-3">
          <Row tone={!last ? "idle" : last.passed ? "ok" : last.status === "failed" ? "bad" : "warn"} title={!last ? "Tests have not been run" : `Last test run: ${last.status.replace(/_/g, " ")}`}>
            {!last ? <>Nothing has been executed for this project, so there is no pass/fail information. <Link className="text-primary hover:underline" href="/testing">Open Testing</Link></> : <>{last.summary} <Link className="text-primary hover:underline" href="/testing">Details</Link></>}
          </Row>
          {ins && <Row tone={ins.risks.untested_modules.length ? "warn" : "ok"} title={ins.risks.untested_modules.length ? `${ins.risks.untested_modules.length} module${ins.risks.untested_modules.length === 1 ? "" : "s"} no test reaches` : "Every module is reached by a test"}>
            {ins.risks.untested_modules.length > 0 && <span className="flex flex-wrap gap-x-2">{ins.risks.untested_modules.slice(0, 4).map((f) => <FileLink key={f} path={f} />)}</span>}</Row>}
          {ins && ins.risks.long_functions.length > 0 && <Row tone="warn" title="Very long functions">{ins.risks.long_functions.slice(0, 3).map((f) => <span key={f.qualname} className="block"><FileLink path={f.file} line={f.line}>{f.qualname}</FileLink> · {f.lines} lines</span>)}</Row>}
          {ins && ins.risks.parse_errors.length > 0 && <Row tone="warn" title={`${ins.risks.parse_errors.length} file(s) could not be parsed`}>{ins.risks.parse_errors.slice(0, 3).join(", ")}. Their structure is missing from the graphs.</Row>}
          {ins && ins.risks.todos > 0 && <Row tone="idle" title={`${nf(ins.risks.todos)} TODO / FIXME markers`} />}
          <Row tone={!quality.data ? "idle" : high.length ? "bad" : "ok"} title={!quality.data ? "No quality scan yet" : high.length ? `${high.length} high-severity finding${high.length === 1 ? "" : "s"} in the last scan` : "No high-severity findings in the last scan"}>
            {!quality.data ? <Link className="text-primary hover:underline" href="/quality">Run a scan</Link> : high.slice(0, 2).map((f, i) => <span key={i} className="block truncate"><FileLink path={f.file} line={f.line} /> {f.message}</span>)}
          </Row>
        </ul>
        <div className="mt-3 flex gap-2"><Button asChild size="sm" variant="outline"><Link href="/review"><ScanSearch />AI code review</Link></Button><Button asChild size="sm" variant="outline"><Link href="/testing"><FlaskConical />Tests</Link></Button></div>
      </CardBody>
    </Card>
  );
}

function AgentActivity({ repoId }: { repoId: string }) {
  const runs = useIde((s) => s.runs);
  const active = useActiveIndexing(true);
  const idx = active.data?.[repoId];
  const recent = [...runs].reverse().slice(0, 5);
  return (
    <Card className="h-full">
      <CardHeader title="Agent activity" description="Indexing, and AI investigations from this session" icon={<ActivityIcon className="size-4" />} actions={<Button asChild size="xs" variant="ghost"><Link href="/chat">Open chat <ArrowRight /></Link></Button>} />
      <CardBody className="space-y-3">
        {idx?.state === "indexing" ? <div className="space-y-1.5 rounded-lg bg-info/8 px-3 py-2"><div className="flex items-center gap-2 text-xs font-medium text-info"><Loader2 className="size-3.5 animate-spin" />Indexing: {idx.phase ?? "working"}</div>{idx.total ? <Progress value={((idx.done ?? 0) / idx.total) * 100} label="Indexing progress" /> : null}</div>
          : idx?.state === "error" ? <div className="rounded-lg bg-destructive/8 px-3 py-2 text-xs text-destructive">Indexing failed: {idx.error}</div> : null}
        {recent.length === 0 ? <EmptyState className="py-6" icon={<Sparkles className="size-5" />} title="No AI investigations yet" description="Ask a question or investigate an error. Each run shows up here with its real status and duration." />
          : <ul className="space-y-1">{recent.map((r) => <li key={r.id}><Link href="/chat" className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-[13px] hover:bg-accent/60"><StatusDot tone={r.state === "running" ? "running" : r.state === "done" ? "success" : r.state === "error" ? "destructive" : "muted"} /><Badge variant="secondary" className="capitalize">{r.mode}</Badge><span className="min-w-0 flex-1 truncate">{r.label}</span><span className="text-xs text-muted-foreground">{r.ended ? fmtMs(r.ended - r.started) : "running"}</span></Link></li>)}</ul>}
      </CardBody>
    </Card>
  );
}

export function Dashboard({ repoId }: { repoId: string }) {
  const stats = useStats(repoId);
  const health = useHealth();
  const insights = useQuery({ queryKey: ["insights", repoId], queryFn: () => api.insights(repoId) });
  const s = stats.data;
  const ins = insights.data;
  return (
    <div className="mx-auto max-w-[1280px] space-y-4 p-4 sm:p-6">
      <Tile>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0"><h1 className="truncate text-xl font-semibold">{s?.repo.name ?? "Project"}</h1>
            <p className="mt-0.5 text-[13px] text-muted-foreground">{s ? `${nf(s.files)} files · ${nf(s.lines)} lines · ${nf(s.symbols.functions + s.symbols.methods)} functions · ${nf(s.symbols.classes)} classes · indexed ${ago(s.indexing.indexed_at)}` : "Loading…"}</p></div>
          <div className="flex items-center gap-2">{health.data && <Badge variant={health.data.llm_provider === "mock" ? "warning" : "success"}>{health.data.llm_provider === "mock" ? "Offline mock model" : `AI: ${health.data.llm_provider}`}</Badge>}<Button asChild size="sm"><Link href="/review"><ScanSearch />Review code</Link></Button><Button asChild size="sm" variant="outline"><Link href="/chat"><MessagesSquare />Ask the agent</Link></Button><Button asChild size="sm" variant="outline"><Link href="/architecture?p=system"><Waypoints />Explore in 3D</Link></Button></div>
        </div>
        {s && s.languages.length > 0 && <div className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-secondary" role="img" aria-label="Language mix">{s.languages.filter((l) => l.lines > 0).slice(0, 6).map((l, i) => <div key={l.language} title={`${l.language}: ${nf(l.lines)} lines`} style={{ width: `${(l.lines / Math.max(1, s.lines)) * 100}%`, background: `hsl(var(--chart-${(i % 6) + 1}))` }} />)}</div>}
      </Tile>
      {stats.isError ? <ErrorState title="Couldn’t load repository statistics" error={stats.error} onRetry={() => stats.refetch()} /> : (
        <>
          <Tile i={1}><ReviewCard repoId={repoId} /></Tile>
          <Tile i={2}><Understanding repoId={repoId} ins={ins} stats={s} /></Tile>
          {insights.isError && <ErrorState title="Couldn’t analyse the project structure" error={insights.error} onRetry={() => insights.refetch()} />}
          <div className="grid gap-4 lg:grid-cols-5"><Tile i={2} className="lg:col-span-3"><ArchitectureGlance repoId={repoId} ins={ins} /></Tile><Tile i={3} className="lg:col-span-2"><StartHere ins={ins} /></Tile></div>
          <div className="grid gap-4 lg:grid-cols-2"><Tile i={4}><Risks repoId={repoId} ins={ins} /></Tile><Tile i={5}><AgentActivity repoId={repoId} /></Tile></div>
        </>
      )}
    </div>
  );
}
