"use client";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowDown, ArrowUp, ChevronDown, Loader2, Minus, Play, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { QFinding, QualityReport } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Input } from "@/components/ui/input";
import { PageHeader, Progress, Stat, Switch, Table, Td, Th } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChartTip, FileLink, SEV_COLOR, SEV_ORDER, ScoreRing, SeverityBadge, nf, pct } from "@/components/common/bits";
import { ago } from "@/components/shell/IndexStatus";

const AN_TONE = { ok: "success", issues: "warning", unavailable: "secondary", skipped: "secondary", timeout: "warning", error: "destructive" } as const;
const tone = (s: number) => (s >= 80 ? "success" : s >= 60 ? "warning" : "destructive") as "success" | "warning" | "destructive";

function FindingRow({ f }: { f: QFinding }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr onClick={() => setOpen(!open)} className="cursor-pointer hover:bg-accent/40">
        <Td><SeverityBadge s={f.severity} /></Td><Td className="font-mono text-xs">{f.tool}</Td><Td className="capitalize text-xs text-muted-foreground">{f.category}</Td>
        <Td className="max-w-[360px] truncate text-[13px]">{f.message}</Td><Td className="font-mono text-xs text-muted-foreground">{f.file}{f.line ? `:${f.line}` : ""}</Td><Td><ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} /></Td>
      </tr>
      {open && <tr><td colSpan={6} className="border-b bg-surface/50 px-4 py-3 text-xs"><div className="space-y-2"><p className="break-words text-[13px]">{f.message}</p><div className="flex flex-wrap items-center gap-2">{f.code && <Badge variant="outline" className="font-mono">{f.code}</Badge>}{f.cwe && <Badge variant="outline">{f.cwe}</Badge>}{f.blocking && <Badge variant="destructive">blocking</Badge>}{f.file && <FileLink path={f.file} line={f.line || undefined} />}</div>{f.fix && <p className="rounded-lg border border-success/25 bg-success/6 p-2.5">{f.fix}</p>}</div></td></tr>}
    </>
  );
}

export function QualityPage({ repoId }: { repoId: string }) {
  const qc = useQueryClient();
  const latest = useQuery({ queryKey: ["quality-latest", repoId], queryFn: () => api.qualityLatest(repoId), retry: false });
  const history = useQuery({ queryKey: ["quality-history", repoId], queryFn: () => api.qualityHistory(repoId), retry: false });
  const info = useQuery({ queryKey: ["quality-info", repoId], queryFn: () => api.qualityInfo(repoId), retry: false });
  const [coverage, setCoverage] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);
  const [fsev, setFsev] = useState("all");
  const [ftool, setFtool] = useState("all");
  const [q, setQ] = useState("");
  const start = useMutation({ mutationFn: () => api.qualityRun(repoId, undefined, coverage), onSuccess: (r) => setJobId(r.id), onError: (e: Error) => toast.error(e.message) });
  const job = useQuery({ queryKey: ["quality-job", jobId], queryFn: () => api.qualityJob(jobId!), enabled: !!jobId, refetchInterval: (qq) => (qq.state.data?.status === "running" || !qq.state.data ? 1000 : false) });
  useEffect(() => {
    if (job.data?.status === "done") { toast.success("Quality scan finished"); qc.invalidateQueries({ queryKey: ["quality-latest", repoId] }); qc.invalidateQueries({ queryKey: ["quality-history", repoId] }); setJobId(null); }
    if (job.data?.status === "error") { toast.error(job.data.error ?? "The scan failed"); setJobId(null); }
  }, [job.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const running = start.isPending || !!jobId;
  const r: QualityReport | null | undefined = latest.data;
  const findings = useMemo(() => (r ? Object.values(r.analyzers).flatMap((a) => a.findings) : []), [r]);
  const shown = useMemo(() => findings.filter((f) => (fsev === "all" || f.severity === fsev) && (ftool === "all" || f.tool === ftool) && (!q || `${f.file} ${f.message} ${f.code}`.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => (SEV_ORDER[a.severity] - SEV_ORDER[b.severity]) || a.file.localeCompare(b.file)).slice(0, 300), [findings, fsev, ftool, q]);
  const sevCounts = (["critical", "high", "medium", "low", "info"] as const).map((s) => ({ name: s, value: findings.filter((f) => f.severity === s).length })).filter((d) => d.value);
  const trend = [...(history.data ?? [])].filter((h) => h.score != null).reverse().map((h) => ({ t: new Date(h.created * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }), score: h.score as number, grade: h.grade }));
  const hist = history.data ?? [];
  const prev = hist.length > 1 ? hist[1] : undefined;
  const delta = r?.score.overall != null && prev?.score != null ? r.score.overall - prev.score : null;
  const tools = [...new Set(findings.map((f) => f.tool))];

  return (
    <div className="mx-auto max-w-[1200px] space-y-4 p-4 sm:p-6">
      <PageHeader title="Code Quality" description="Tests, coverage and static analyzers run in the sandbox and roll up into one score. Dimensions that couldn’t be measured show as n/a, never as zero." icon={<ShieldCheck />}
        actions={<><label className="flex items-center gap-2 text-xs text-muted-foreground"><Switch checked={coverage} onCheckedChange={setCoverage} label="Measure coverage" />Coverage</label><Button onClick={() => start.mutate()} loading={running}><Play />{r ? "Run new scan" : "Run scan"}</Button></>} />
      {job.data && job.data.status === "running" && (
        <Card><CardBody className="space-y-2" role="status" aria-live="polite"><div className="flex items-center gap-2 text-[13px] font-medium"><Loader2 className="size-4 animate-spin text-primary" />Scan in progress</div>
          <ul className="space-y-0.5 text-xs text-muted-foreground">{job.data.progress.slice(-5).map((p, i) => <li key={i}>{p.message}</li>)}</ul></CardBody></Card>
      )}
      {latest.isLoading ? <div className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-64" /></div>
        : latest.isError ? <ErrorState title="Couldn’t load the latest report" error={latest.error} onRetry={() => latest.refetch()} />
        : !r ? <EmptyState icon={<ShieldCheck className="size-5" />} title="No quality scan yet" description={`Runs the project’s tests and ${info.data ? info.data.analyzers.filter((a) => a.applies).length : "the available"} analyzers that apply to it.`} action={<Button onClick={() => start.mutate()} loading={running}><Play />Run scan</Button>} />
        : (
          <>
            <div className="grid gap-4 lg:grid-cols-3">
              <Card><CardHeader title="Overall score" description={`Scanned ${ago(r.created)} · ${r.duration_s.toFixed(0)} s`} /><CardBody className="flex items-center gap-5">
                <ScoreRing value={r.score.overall} grade={r.score.grade} size={112} label="Quality score" />
                <div className="space-y-1.5 text-xs"><div className="flex items-center gap-1.5">{delta == null ? <Minus className="size-3.5 text-muted-foreground" /> : delta >= 0 ? <ArrowUp className="size-3.5 text-success" /> : <ArrowDown className="size-3.5 text-destructive" />}<span className={cn("font-medium tabular-nums", delta != null && (delta >= 0 ? "text-success" : "text-destructive"))}>{delta == null ? "no earlier scan to compare" : `${delta >= 0 ? "+" : ""}${delta.toFixed(0)} vs previous scan`}</span></div>
                  <div className="text-muted-foreground">{r.frameworks.length ? `Frameworks: ${r.frameworks.join(", ")}` : "No test framework detected"}</div>
                  <Badge variant={r.sandbox.isolated ? "success" : "warning"}>{r.sandbox.isolated ? "isolated sandbox" : "not isolated"}</Badge></div></CardBody></Card>
              <Card className="lg:col-span-2"><CardHeader title="Score by dimension" /><CardBody className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
                {Object.entries(r.score.dimensions).map(([k, d]) => <div key={k} className="text-xs"><div className="mb-1 flex justify-between"><span className="font-medium capitalize">{k.replace(/_/g, " ")}</span><span className="tabular-nums text-muted-foreground">{Math.round(d.score)} · weight {Math.round(d.weight * 100)}%</span></div><Progress value={d.score} tone={tone(d.score)} label={k} /><div className="mt-0.5 truncate text-muted-foreground" title={d.detail}>{d.detail}</div></div>)}
                {r.score.not_measured.length > 0 && <div className="text-xs text-muted-foreground sm:col-span-2">Not measured: {r.score.not_measured.join(", ")}</div>}</CardBody></Card>
            </div>
            <div className="grid gap-4 lg:grid-cols-3">
              <Card className="lg:col-span-2"><CardHeader title="Quality trend" description={trend.length > 1 ? `${trend.length} scans` : "Needs at least two scans"} /><CardBody>{trend.length < 2 ? <p className="py-8 text-center text-xs text-muted-foreground">Run another scan later to see how the score changes.</p> : (
                <div className="h-44" role="img" aria-label="Quality score over time"><ResponsiveContainer><AreaChart data={trend} margin={{ left: -18, right: 6, top: 6 }}><defs><linearGradient id="qg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.3} /><stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0} /></linearGradient></defs><CartesianGrid vertical={false} stroke="hsl(var(--border))" /><XAxis dataKey="t" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} /><YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} /><Tooltip content={<ChartTip />} /><Area type="monotone" dataKey="score" name="Score" stroke="hsl(var(--chart-1))" strokeWidth={2} fill="url(#qg)" /></AreaChart></ResponsiveContainer></div>)}</CardBody></Card>
              <Card><CardHeader title="Findings by severity" description={`${findings.length} total`} /><CardBody>{sevCounts.length === 0 ? <p className="py-8 text-center text-xs text-success">No findings.</p> : <div className="h-44" role="img" aria-label="Findings by severity"><ResponsiveContainer><BarChart data={sevCounts} margin={{ left: -24 }}><XAxis dataKey="name" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} /><Tooltip cursor={{ fill: "hsl(var(--accent))" }} content={<ChartTip />} /><Bar dataKey="value" name="Findings" radius={[4, 4, 0, 0]}>{sevCounts.map((d) => <Cell key={d.name} fill={SEV_COLOR[d.name]} />)}</Bar></BarChart></ResponsiveContainer></div>}</CardBody></Card>
            </div>
            <Tabs defaultValue="findings">
              <TabsList className="border-b"><TabsTrigger value="findings">Findings <span className="tabular-nums text-muted-foreground">{findings.length}</span></TabsTrigger><TabsTrigger value="analyzers">Analyzers</TabsTrigger><TabsTrigger value="coverage">Coverage</TabsTrigger><TabsTrigger value="maint">Maintainability</TabsTrigger><TabsTrigger value="tests">Tests</TabsTrigger></TabsList>
              <TabsContent value="findings" className="pt-3"><Card>
                <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
                  {["all", "critical", "high", "medium", "low", "info"].map((s) => <button key={s} aria-pressed={fsev === s} onClick={() => setFsev(s)} className={cn("rounded-md border px-2 py-0.5 text-xs capitalize", fsev === s ? "bg-accent font-medium" : "text-muted-foreground")}>{s}</button>)}
                  <select aria-label="Filter by tool" value={ftool} onChange={(e) => setFtool(e.target.value)} className="h-7 rounded-md border bg-panel px-2 text-xs"><option value="all">All tools</option>{tools.map((t) => <option key={t}>{t}</option>)}</select>
                  <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter…" aria-label="Filter findings" className="ml-auto h-7 w-44" />
                </div>
                {shown.length === 0 ? <p className="px-4 py-8 text-center text-xs text-muted-foreground">No findings match.</p> : <Table><thead><tr><Th>Severity</Th><Th>Tool</Th><Th>Type</Th><Th>Message</Th><Th>Location</Th><Th /></tr></thead><tbody>{shown.map((f, i) => <FindingRow key={i} f={f} />)}</tbody></Table>}
                {findings.length > shown.length && shown.length === 300 && <p className="border-t px-4 py-2 text-[11px] text-muted-foreground">Showing the first 300 findings. Narrow the filters to see others.</p>}
              </Card></TabsContent>
              <TabsContent value="analyzers" className="pt-3"><Card><Table><thead><tr><Th>Analyzer</Th><Th>Category</Th><Th>Status</Th><Th>Findings</Th><Th>Time</Th><Th>Summary</Th></tr></thead><tbody>
                {Object.entries(r.analyzers).map(([name, a]) => <tr key={name}><Td className="font-mono text-xs font-medium">{name}</Td><Td className="capitalize text-xs text-muted-foreground">{a.category}</Td><Td><Badge variant={AN_TONE[a.status]}>{a.status}</Badge></Td><Td className="tabular-nums">{a.findings.length}</Td><Td className="text-xs text-muted-foreground">{(a.duration_ms / 1000).toFixed(1)} s</Td><Td className="max-w-[320px] truncate text-xs text-muted-foreground" title={a.note || a.summary}>{a.note || a.summary}</Td></tr>)}</tbody></Table></Card></TabsContent>
              <TabsContent value="coverage" className="pt-3"><Card><CardBody>{!r.coverage ? <p className="text-xs text-muted-foreground">Coverage wasn’t measured in this scan (switch Coverage on and run again, or the framework doesn’t support it).</p> : (
                <div className="space-y-4"><div className="grid grid-cols-3 gap-4"><Stat label="Overall" value={pct(r.coverage.percent, 1)} /><Stat label="Lines covered" value={nf(r.coverage.covered)} /><Stat label="Lines total" value={nf(r.coverage.total)} /></div>
                  <Table><thead><tr><Th>File</Th><Th>Coverage</Th><Th>Missing lines</Th></tr></thead><tbody>{[...r.coverage.files].sort((a, b) => a.percent - b.percent).slice(0, 30).map((f) => <tr key={f.path}><Td><FileLink path={f.path} /></Td><Td className="w-48"><div className="flex items-center gap-2"><Progress value={f.percent} tone={tone(f.percent)} className="flex-1" label={f.path} /><span className="w-10 text-right text-xs tabular-nums">{pct(f.percent)}</span></div></Td><Td className="max-w-[260px] truncate font-mono text-[11px] text-muted-foreground">{f.missing.slice(0, 14).join(", ")}</Td></tr>)}</tbody></Table></div>)}</CardBody></Card></TabsContent>
              <TabsContent value="maint" className="pt-3"><Card><CardBody>{!r.maintainability.available ? <p className="text-xs text-muted-foreground">Complexity wasn’t measured (the analyzer isn’t available for this project).</p> : (
                <div className="space-y-3"><div className="grid grid-cols-3 gap-4"><Stat label="Functions analysed" value={nf(r.maintainability.functions)} /><Stat label="Too complex or long" value={nf(r.maintainability.too_complex_or_long)} /><Stat label="Average complexity" value={r.maintainability.avg_complexity?.toFixed(1) ?? "–"} /></div>
                  {r.maintainability.worst && r.maintainability.worst.length > 0 && <Table><thead><tr><Th>Function</Th><Th>Location</Th><Th>Length</Th><Th>Complexity</Th></tr></thead><tbody>{r.maintainability.worst.map((w, i) => <tr key={i}><Td className="font-mono text-xs">{w.name}</Td><Td><FileLink path={w.file} line={w.line} /></Td><Td className="tabular-nums">{w.length}</Td><Td className="tabular-nums">{w.complexity}</Td></tr>)}</tbody></Table>}</div>)}</CardBody></Card></TabsContent>
              <TabsContent value="tests" className="pt-3"><Card><CardBody className="space-y-2">{r.tests.length === 0 ? <p className="text-xs text-muted-foreground">No tests ran in this scan.</p> : r.tests.map((t, i) => <div key={i} className="flex items-center gap-2 rounded-lg bg-secondary/50 px-3 py-2 text-xs"><Badge variant={t.passed ? "success" : t.status === "failed" ? "destructive" : "warning"} className="capitalize">{t.status.replace(/_/g, " ")}</Badge><span className="font-medium">{t.framework}</span><span className="min-w-0 flex-1 truncate text-muted-foreground">{t.summary}</span></div>)}</CardBody></Card></TabsContent>
            </Tabs>
            {r.notes.length > 0 && <ul className="space-y-0.5 text-xs text-muted-foreground">{r.notes.map((n, i) => <li key={i}>• {n}</li>)}</ul>}
          </>
        )}
    </div>
  );
}
