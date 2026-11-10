"use client";
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight, Boxes, Check, ChevronsDownUp, FileCode2, FlaskConical, FunctionSquare, Loader2, Milestone, Search, Sparkles, X } from "lucide-react";
import { api } from "@/lib/api";
import { useOpenFile } from "@/hooks/useOpen";
import { fuzzy, cn, basename } from "@/lib/utils";
import type { ExplainResponse, SgEdge, SystemGraph } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/common/Markdown";
import { parseLines } from "@/lib/utils";
import type { Adjacency, Layout } from "./layout3d";

export type Sel = { kind: "cluster" | "file" | "symbol"; id: string };
export interface TraceState { from: string | null; to: string | null; undirected: boolean; path: SgEdge[] | null; picking: boolean }

const TYPE_LABEL: Record<string, string> = { import: "imports", call: "calls", file_call: "calls", inherit: "extends", test: "tests" };

function Rel({ e, other, onSelect, g }: { e: SgEdge; other: string; onSelect: (id: string) => void; g: Maps }) {
  const label = g.label(other);
  return (
    <li><button onClick={() => onSelect(other)} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] hover:bg-accent/60">
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <Badge variant="outline" className="shrink-0">{TYPE_LABEL[e.type]}</Badge>
      <Badge variant={e.verified ? "success" : "warning"} className="shrink-0" title={e.basis}>{e.verified ? "verified" : "inferred"}</Badge>
    </button></li>
  );
}
export interface Maps { label: (id: string) => string; kindOf: (id: string) => "cluster" | "file" | "symbol" | undefined }

function RelList({ title, icon, edges, side, onSelect, g }: { title: string; icon: React.ReactNode; edges: SgEdge[]; side: "source" | "target"; onSelect: (id: string) => void; g: Maps }) {
  if (!edges.length) return null;
  return (
    <div><div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{icon}{title}<span className="tabular-nums">({edges.length})</span></div>
      <ul className="mb-3">{edges.slice(0, 14).map((e, i) => <Rel key={i} e={e} other={side === "source" ? e.source : e.target} onSelect={onSelect} g={g} />)}</ul>
      {edges.length > 14 && <div className="-mt-2 mb-3 px-1.5 text-[11px] text-muted-foreground">+{edges.length - 14} more</div>}
    </div>
  );
}

function Code({ repoId, path, around }: { repoId: string; path: string; around?: [number, number] }) {
  const q = useQuery({ queryKey: ["file", repoId, path], queryFn: () => api.file(repoId, path), staleTime: 60_000 });
  const open = useOpenFile();
  if (q.isLoading) return <Skeleton className="h-28" />;
  if (!q.data) return <p className="text-xs text-muted-foreground">Can’t show this file{q.error ? `: ${(q.error as Error).message}` : ""}.</p>;
  const all = q.data.text.split("\n");
  const start = around ? Math.max(1, around[0] - 1) : 1;
  const end = Math.min(all.length, around ? Math.min(around[1], around[0] + 30) : start + 34);
  return (
    <div className="overflow-hidden rounded-lg border bg-surface">
      <pre className="max-h-64 overflow-auto p-2 font-mono text-[11.5px] leading-relaxed">{all.slice(start - 1, end).map((l, i) => <div key={i} className="flex gap-3"><span className="w-8 shrink-0 select-none text-right text-muted-foreground">{start + i}</span><span className="whitespace-pre">{l || " "}</span></div>)}</pre>
      <button onClick={() => open(path, start)} className="w-full border-t px-2 py-1.5 text-left text-[11px] text-primary hover:bg-accent/50">Open the full file in the Code Explorer</button>
    </div>
  );
}

export function InfoPanel({ repoId, graph, layout, adj, sel, focusCluster, trace, setTrace, runTrace, onSelect, onEnter, onExit, onClose, g, targets }: {
  repoId: string; graph: SystemGraph; layout: Layout; adj: Adjacency; sel: Sel; focusCluster: string | null; trace: TraceState; setTrace: (t: TraceState) => void; runTrace: (from: string, to: string, undirected: boolean) => void;
  onSelect: (id: string) => void; onEnter: (id: string) => void; onExit: () => void; onClose: () => void; g: Maps; targets: { id: string; label: string; hint: string }[];
}) {
  const open = useOpenFile();
  const [tq, setTq] = useState("");
  const explain = useMutation({
    mutationFn: (): Promise<ExplainResponse> => api.explain(repoId, sel.kind === "cluster" ? "folder" : sel.kind, sel.kind === "symbol" ? [] : sel.kind === "cluster" ? (layout.clusters.find((c) => c.id === sel.id)?.files ?? []).slice(0, 40) : [sel.id], sel.kind === "symbol" ? [sel.id] : []),
  });
  const cluster = sel.kind === "cluster" ? layout.clusters.find((c) => c.id === sel.id) : undefined;
  const file = sel.kind === "file" ? layout.files.get(sel.id)?.file : undefined;
  const sym = sel.kind === "symbol" ? graph.symbols.find((s) => s.id === sel.id) : undefined;
  const filePath = file?.id ?? sym?.file;
  const out = adj.out.get(sel.id) ?? [], inc = adj.inc.get(sel.id) ?? [];
  const clusterDeps = useMemo(() => {
    if (!cluster) return null;
    const set = new Set(cluster.files); const to = new Map<string, number>(), from = new Map<string, number>();
    for (const e of graph.edges) {
      if (e.type === "call" || e.type === "inherit") continue;
      const a = set.has(e.source), b = set.has(e.target); if (a === b) continue;
      const other = layout.clusterOf.get(a ? e.target : e.source); if (!other) continue;
      const m = a ? to : from; m.set(other, (m.get(other) ?? 0) + 1);
    }
    return { to: [...to.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6), from: [...from.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6) };
  }, [cluster, graph.edges, layout.clusterOf]);
  const fileSyms = file ? layout.symbolsByFile.get(file.id) ?? [] : [];
  const hits = useMemo(() => tq.trim().length < 2 ? [] : targets.map((t) => ({ t, s: Math.max(fuzzy(tq, t.label), fuzzy(tq, t.hint)) })).filter((x) => x.s >= 0 && x.t.id !== trace.from).sort((a, b) => b.s - a.s).slice(0, 6).map((x) => x.t), [tq, targets, trace.from]);
  const title = cluster ? cluster.label : file ? file.name : sym?.qualname ?? sel.id;
  const traceHere = trace.from === sel.id;
  const res = explain.data;

  return (
    <aside className="flex h-full min-h-0 flex-col" aria-label="Details">
      <div className="flex items-start gap-2 border-b px-4 py-3">
        <span className="mt-0.5 text-primary">{cluster ? <Boxes className="size-4" /> : file?.is_test ? <FlaskConical className="size-4" /> : sym ? <FunctionSquare className="size-4" /> : <FileCode2 className="size-4" />}</span>
        <div className="min-w-0 flex-1"><div className="truncate text-[13px] font-semibold">{title}</div><div className="truncate font-mono text-[11px] text-muted-foreground">{cluster ? `${cluster.files.length} files` : sym ? `${sym.file}:${sym.start}` : file?.id}</div></div>
        <button onClick={onClose} aria-label="Close details" className="text-muted-foreground hover:text-foreground"><X className="size-4" /></button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="secondary" className="capitalize">{cluster ? "folder" : sym?.kind ?? "file"}</Badge>
          {file?.language && <Badge variant="outline">{file.language}</Badge>}{file && <Badge variant="outline">{file.lines} lines</Badge>}
          {file?.is_test && <Badge variant="success">test file</Badge>}{file?.entry && <Badge variant="warning">{file.entry === "route" ? "entry: defines routes" : "entry point (by name)"}</Badge>}
          {sym?.route && <Badge variant="info">{sym.route}</Badge>}
          {cluster && cluster.tests > 0 && <Badge variant="success">{cluster.tests} test files</Badge>}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {cluster && (focusCluster === cluster.id ? <Button size="xs" variant="secondary" onClick={onExit}><ChevronsDownUp />Exit folder</Button> : <Button size="xs" onClick={() => onEnter(cluster.id)}><ChevronsDownUp />Enter folder</Button>)}
          {filePath && <Button size="xs" variant="outline" onClick={() => open(filePath, sym?.start, sym?.end)}><FileCode2 />Open code</Button>}
          <Button size="xs" variant="outline" loading={explain.isPending} onClick={() => explain.mutate()}><Sparkles />Explain with AI</Button>
          {!cluster && <Button size="xs" variant={traceHere ? "secondary" : "outline"} onClick={() => setTrace({ from: sel.id, to: null, undirected: trace.undirected, path: null, picking: true })}><Milestone />Trace path…</Button>}
        </div>

        {(explain.isPending || res || explain.isError) && (
          <div className="rounded-lg border bg-panel p-3">
            <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground"><Sparkles className="size-3" />AI explanation</div>
            {explain.isPending ? <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" />Reading the code and the graph relationships…</div>
              : explain.isError ? <p className="text-xs text-destructive">{(explain.error as Error).message}</p>
              : res?.state === "unavailable" ? <p className="text-xs text-warning">Offline mode: {res.reason}</p>
              : res ? <><Markdown sources={res.sources} onCite={(n) => { const s = res.sources?.find((x) => x.cite === n); if (s) open(s.file, parseLines(s.lines)[0]); }}>{res.answer ?? ""}</Markdown><div className="mt-2 text-[11px] text-muted-foreground">{res.llm} · {res.sources?.length ?? 0} snippets retrieved</div></> : null}
          </div>
        )}

        {trace.from && (trace.picking || trace.path !== null || trace.to) && (
          <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-xs">
            <div className="mb-1.5 flex items-center justify-between"><span className="font-medium">Trace from <span className="font-mono">{g.label(trace.from)}</span></span><button aria-label="Clear trace" onClick={() => setTrace({ from: null, to: null, undirected: trace.undirected, path: null, picking: false })}><X className="size-3.5" /></button></div>
            {trace.picking && (<>
              <div className="relative"><Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" /><Input autoFocus value={tq} onChange={(e) => setTq(e.target.value)} placeholder="Trace to… (file or function)" aria-label="Trace destination" className="h-7 pl-7" /></div>
              {hits.length > 0 && <ul className="mt-1 rounded-md border bg-panel p-1">{hits.map((t) => <li key={t.id}><button className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left hover:bg-accent" onClick={() => { setTq(""); runTrace(trace.from!, t.id, trace.undirected); }}><span className="truncate">{t.label}</span><span className="ml-auto truncate font-mono text-[10.5px] text-muted-foreground">{t.hint}</span></button></li>)}</ul>}
              <label className="mt-2 flex items-center gap-1.5 text-muted-foreground"><input type="checkbox" className="accent-[hsl(var(--primary))]" checked={trace.undirected} onChange={(e) => { setTrace({ ...trace, undirected: e.target.checked }); if (trace.to) runTrace(trace.from!, trace.to, e.target.checked); }} />Also follow relationships backwards</label>
            </>)}
            {trace.to && trace.path === null && <p className="mt-2 text-warning">No path from {g.label(trace.from)} to {g.label(trace.to)} through the parsed relationships (imports, calls, inheritance). Dynamic dispatch, configuration or reflection can connect code the parser cannot see.</p>}
            {trace.path && (trace.path.length === 0 ? <p className="mt-2">Same node.</p> : (
              <ol className="mt-2 space-y-1">{trace.path.map((e, i) => <li key={i} className="flex items-center gap-1.5"><Check className="size-3 shrink-0 text-success" /><span className="truncate font-mono">{g.label(e.source)}</span><span className="shrink-0 text-muted-foreground">{TYPE_LABEL[e.type]}</span><span className="truncate font-mono">{g.label(e.target)}</span>{!e.verified && <Badge variant="warning">inferred</Badge>}</li>)}</ol>
            ))}
          </div>
        )}

        {cluster && clusterDeps && (<>
          <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Languages</div><div className="flex flex-wrap gap-1.5">{Object.entries(cluster.languages).map(([l, n]) => <Badge key={l} variant="outline">{l} · {n}</Badge>)}</div></div>
          {clusterDeps.to.length > 0 && <div><div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground"><ArrowUpRight className="size-3" />Depends on</div><ul className="mb-2">{clusterDeps.to.map(([c, n]) => <li key={c}><button onClick={() => onSelect(c)} className="flex w-full justify-between rounded-md px-1.5 py-1 text-[13px] hover:bg-accent/60"><span className="truncate">{c}</span><span className="tabular-nums text-muted-foreground">{n}</span></button></li>)}</ul></div>}
          {clusterDeps.from.length > 0 && <div><div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground"><ArrowDownLeft className="size-3" />Used by</div><ul className="mb-2">{clusterDeps.from.map(([c, n]) => <li key={c}><button onClick={() => onSelect(c)} className="flex w-full justify-between rounded-md px-1.5 py-1 text-[13px] hover:bg-accent/60"><span className="truncate">{c}</span><span className="tabular-nums text-muted-foreground">{n}</span></button></li>)}</ul></div>}
          <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Files</div><ul>{cluster.files.slice(0, 16).map((f) => <li key={f}><button onClick={() => onSelect(f)} className="w-full truncate rounded-md px-1.5 py-1 text-left font-mono text-[12px] hover:bg-accent/60">{basename(f)}</button></li>)}</ul>{cluster.files.length > 16 && <div className="px-1.5 text-[11px] text-muted-foreground">+{cluster.files.length - 16} more. Enter the folder to see them all.</div>}</div>
        </>)}

        {file && (<>
          {file.routes.length > 0 && <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Routes</div><ul className="space-y-0.5 text-xs">{file.routes.map((r, i) => <li key={i} className="flex items-center gap-2"><Badge variant="info" className="font-mono">{r.method}</Badge><span className="font-mono">{r.path}</span><span className="truncate text-muted-foreground">{r.handler}</span></li>)}</ul></div>}
          {fileSyms.length > 0 && <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Functions & classes ({file.symbols})</div><ul>{fileSyms.slice(0, 14).map((s) => <li key={s.id}><button onClick={() => onSelect(s.id)} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] hover:bg-accent/60"><FunctionSquare className="size-3.5 text-muted-foreground" /><span className="truncate">{s.qualname}</span><span className="ml-auto font-mono text-[11px] text-muted-foreground">{s.start}</span></button></li>)}</ul></div>}
          <RelList title="Imports" icon={<ArrowUpRight className="size-3" />} edges={out.filter((e) => e.type === "import" || (e.type === "test"))} side="target" onSelect={onSelect} g={g} />
          <RelList title="Imported by" icon={<ArrowDownLeft className="size-3" />} edges={inc.filter((e) => e.type === "import")} side="source" onSelect={onSelect} g={g} />
          <RelList title="Tests" icon={<FlaskConical className="size-3" />} edges={inc.filter((e) => e.type === "test")} side="source" onSelect={onSelect} g={g} />
          <RelList title="Calls into other files" icon={<ArrowUpRight className="size-3" />} edges={out.filter((e) => e.type === "file_call")} side="target" onSelect={onSelect} g={g} />
          <RelList title="Called from other files" icon={<ArrowDownLeft className="size-3" />} edges={inc.filter((e) => e.type === "file_call")} side="source" onSelect={onSelect} g={g} />
          {file.external.length > 0 && <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">External packages</div><div className="flex flex-wrap gap-1.5">{file.external.map((x) => <Badge key={x} variant="outline">{x}</Badge>)}</div></div>}
          <Code repoId={repoId} path={file.id} />
        </>)}

        {sym && (<>
          <RelList title="Called by" icon={<ArrowDownLeft className="size-3" />} edges={inc.filter((e) => e.type === "call")} side="source" onSelect={onSelect} g={g} />
          <RelList title="Calls" icon={<ArrowUpRight className="size-3" />} edges={out.filter((e) => e.type === "call")} side="target" onSelect={onSelect} g={g} />
          <RelList title="Extends" icon={<ArrowUpRight className="size-3" />} edges={out.filter((e) => e.type === "inherit")} side="target" onSelect={onSelect} g={g} />
          <RelList title="Subclasses" icon={<ArrowDownLeft className="size-3" />} edges={inc.filter((e) => e.type === "inherit")} side="source" onSelect={onSelect} g={g} />
          {out.length + inc.length === 0 && <p className="text-xs text-muted-foreground">No resolved callers or callees were found for this symbol. It may be called dynamically or from outside the repository.</p>}
          <Code repoId={repoId} path={sym.file} around={[sym.start, sym.end]} />
        </>)}
      </div>
    </aside>
  );
}
