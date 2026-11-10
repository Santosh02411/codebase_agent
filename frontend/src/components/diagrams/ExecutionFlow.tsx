"use client";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronsUpDown, ListTree, Route as RouteIcon, Search, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import { useOpenFile } from "@/hooks/useOpen";
import { basename, cn, fuzzy } from "@/lib/utils";
import type { FlowResult } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { clusterColor } from "@/components/arch3d/layout3d";

const COL = 190, ROW = 38, HEAD = 62;

/** UML-style sequence diagram: one lifeline per file, one arrow per call, in the order the calls appear in the source. */
function Sequence({ flow }: { flow: FlowResult }) {
  const openFile = useOpenFile();
  const parts = flow.participants;
  const idx = new Map(parts.map((p, i) => [p.file, i]));
  const x = (file: string) => 20 + (idx.get(file) ?? 0) * COL + COL / 2;
  const h = HEAD + (flow.steps.length + 1) * ROW + 30;
  const w = 40 + parts.length * COL;
  return (
    <div className="overflow-auto p-4">
      <svg width={w} height={h} className="max-w-none" role="img" aria-label="Sequence diagram of the call flow">
        <defs><marker id="sq" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0L10 5L0 10z" className="fill-foreground" /></marker></defs>
        {parts.map((p, i) => (
          <g key={p.file}>
            <line x1={x(p.file)} y1={HEAD - 6} x2={x(p.file)} y2={h - 12} className="stroke-border" strokeDasharray="4 4" />
            <rect x={20 + i * COL + 8} y={6} width={COL - 16} height={46} rx={8} className={cn("fill-panel", p.file ? "stroke-primary/50" : "stroke-border")} strokeWidth={1.4} />
            <text x={x(p.file)} y={26} textAnchor="middle" className="fill-foreground text-[12.5px] font-semibold">{p.label.length > 22 ? p.label.slice(0, 21) + "…" : p.label}</text>
            <text x={x(p.file)} y={42} textAnchor="middle" className="fill-muted-foreground text-[10px]">{p.file ? (p.file.includes("/") ? p.file.slice(0, p.file.lastIndexOf("/")).slice(-24) : "(root)") : "not in this repository"}</text>
          </g>
        ))}
        <text x={x(flow.root.file)} y={HEAD + 12} textAnchor="middle" className="fill-primary text-[11px] font-medium">▶ {flow.root.qualname}()</text>
        {flow.steps.map((s, i) => {
          const y = HEAD + (i + 1) * ROW + 10;
          const a = x(s.from_file), b = x(s.to_file);
          const self = s.from_file === s.to_file;
          return (
            <g key={i} className={s.resolved ? "cursor-pointer" : ""} onClick={() => s.resolved && openFile(s.to_file, s.to_line)}>
              <rect x={Math.min(a, b) - 4} y={y - 17} width={Math.abs(b - a) + 8 || 40} height={24} fill="transparent" />
              <text x={self ? a + 40 : (a + b) / 2} y={y - 6} textAnchor={self ? "start" : "middle"} className={cn("text-[11.5px]", s.resolved ? "fill-foreground" : "fill-muted-foreground")}>{i + 1}. {s.label.length > 30 ? s.label.slice(0, 29) + "…" : s.label}{s.resolved ? (s.kind === "render" ? "  (renders)" : "") : "  (unresolved)"}</text>
              {self ? <path d={`M${a},${y} h30 v14 h-30`} fill="none" strokeWidth={1.4} className="stroke-foreground" markerEnd="url(#sq)" />
                : <line x1={a} y1={y} x2={b + (b > a ? -3 : 3)} y2={y} strokeWidth={1.4} strokeDasharray={s.resolved && s.verified ? undefined : "5 4"} className="stroke-foreground" markerEnd="url(#sq)" />}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Top-to-bottom flowchart of the same steps (indentation = call depth). */
function Chart({ flow }: { flow: FlowResult }) {
  const openFile = useOpenFile();
  const colors = useMemo(() => new Map(flow.participants.map((p, i) => [p.file, clusterColor(i)])), [flow]);
  return (
    <div className="mx-auto max-w-3xl p-5">
      <div className="flex flex-col items-start">
        <div className="rounded-full bg-primary px-4 py-1.5 text-[13px] font-semibold text-primary-foreground">Start: {flow.root.qualname}()</div>
        {flow.steps.map((s, i) => (
          <div key={i} className="flex flex-col" style={{ marginLeft: (s.depth - 1) * 36 }}>
            <div className="ml-6 h-5 w-px bg-border" />
            <button disabled={!s.resolved} onClick={() => openFile(s.to_file, s.to_line)} style={{ borderLeftColor: colors.get(s.to_file) }}
              className={cn("flex min-w-[260px] items-center gap-3 rounded-lg border border-l-4 bg-panel px-3 py-2 text-left shadow-card transition-colors", s.resolved ? "hover:bg-accent/50" : "border-dashed opacity-75")}>
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-secondary text-[11px] font-semibold">{i + 1}</span>
              <span className="min-w-0"><span className="block text-[13px] font-medium">{s.to}{s.resolved ? (s.kind === "render" ? " (renders)" : "()") : ""}</span><span className="block text-[11px] text-muted-foreground">{s.resolved ? `${basename(s.to_file)}:${s.to_line} · called from ${s.from}` : `called from ${s.from}. Not resolved to code in this repository (library or dynamic call)`}</span></span>
              {s.resolved && !s.verified && <Badge variant="warning">inferred</Badge>}
            </button>
          </div>
        ))}
        {flow.truncated && <p className="mt-3 text-xs text-muted-foreground">Shown the first {flow.steps.length} steps. Lower the depth or pick a narrower starting function to see the rest.</p>}
      </div>
    </div>
  );
}

interface Item { id: string; label: string; sub: string; group: string }

/** A dropdown of everything you can start from (routes, entry points, most-called functions, every function), with a search box inside it. */
function StartPicker({ repoId, value, onPick }: { repoId: string; value: string | null; onPick: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const g = useQuery({ queryKey: ["system-graph", repoId], queryFn: () => api.graphSystem(repoId) });
  const ins = useQuery({ queryKey: ["insights", repoId], queryFn: () => api.insights(repoId) });
  const groups = useMemo(() => {
    const syms = (g.data?.symbols ?? []).filter((s) => s.kind === "function" || s.kind === "method" || s.kind === "class" || s.kind === "variable");
    const entryFiles = new Set((g.data?.files ?? []).filter((f) => f.entry).map((f) => f.id));
    const by = new Map(syms.map((s) => [`${s.file}::${s.name}`, s]));
    const routes: Item[] = (ins.data?.routes ?? []).flatMap((r) => { const s = by.get(`${r.file}::${r.handler.split(".").pop()}`); return s ? [{ id: s.id, label: `${r.method} ${r.path}`, sub: `${s.qualname} · ${s.file}`, group: "API routes" }] : []; });
    const entries: Item[] = syms.filter((s) => entryFiles.has(s.file)).slice(0, 20).map((s) => ({ id: s.id, label: s.qualname, sub: s.file, group: "Entry points" }));
    const hubs: Item[] = [...syms].sort((a, b) => b.callers - a.callers).filter((s) => s.callers > 0).slice(0, 10).map((s) => ({ id: s.id, label: s.qualname, sub: `${s.callers} callers · ${s.file}`, group: "Most called" }));
    const all: Item[] = [...syms].sort((a, b) => a.file.localeCompare(b.file) || a.start - b.start).map((s) => ({ id: s.id, label: s.qualname, sub: `${s.kind} · ${s.file}:${s.start}`, group: "All functions and components" }));
    return { routes, entries, hubs, all, byId: new Map(syms.map((s) => [s.id, s])) };
  }, [g.data, ins.data]);
  const cur = value ? groups.byId.get(value) : null;
  const sections = useMemo(() => {
    const f = (xs: Item[], cap: number) => (q.trim() ? xs.map((x) => ({ x, s: Math.max(fuzzy(q, x.label), fuzzy(q, x.sub)) })).filter((r) => r.s >= 0).sort((a, b) => b.s - a.s).slice(0, cap).map((r) => r.x) : xs.slice(0, cap));
    return [["API routes", f(groups.routes, 30)], ["Entry points", f(groups.entries, 20)], ["Most called", q.trim() ? [] : f(groups.hubs, 10)], ["All functions and components", f(groups.all, q.trim() ? 40 : 60)]] as [string, Item[]][];
  }, [groups, q]);
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open} className="flex h-8 w-72 items-center gap-2 rounded-md border border-input bg-panel px-2.5 text-left text-[13px] hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
        <Workflow className="size-3.5 shrink-0 text-muted-foreground" /><span className="min-w-0 flex-1 truncate">{cur ? <><b className="font-medium">{cur.qualname}</b> <span className="text-muted-foreground">{cur.file}</span></> : <span className="text-muted-foreground">Choose where to start…</span>}</span><ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-40 mt-1 w-[26rem] max-w-[90vw] overflow-hidden rounded-xl bg-panel shadow-pop" role="listbox">
            <div className="relative border-b p-2"><Search className="pointer-events-none absolute left-4 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" /><Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search routes, functions, components…" aria-label="Search where to start" className="h-8 pl-8" /></div>
            <div className="max-h-96 overflow-y-auto p-1.5">
              {g.isLoading ? <div className="p-4 text-xs text-muted-foreground">Loading…</div> : sections.every(([, xs]) => !xs.length) ? <div className="p-4 text-center text-xs text-muted-foreground">Nothing matches “{q}”.</div> : sections.map(([title, xs]) => xs.length > 0 && (
                <div key={title}><div className="px-2 pb-1 pt-2 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">{title}</div>
                  {xs.map((x) => <button key={title + x.id} role="option" aria-selected={x.id === value} onClick={() => { onPick(x.id); setOpen(false); setQ(""); }} className={cn("flex w-full flex-col rounded-md px-2 py-1.5 text-left hover:bg-accent", x.id === value && "bg-accent")}><span className="truncate text-[13px] font-medium">{x.label}</span><span className="truncate font-mono text-[11px] text-muted-foreground">{x.sub}</span></button>)}</div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export function ExecutionFlow({ repoId }: { repoId: string }) {
  const [view, setView] = useState<"sequence" | "chart">("sequence");
  const [depth, setDepth] = useState(3);
  const [sid, setSid] = useState<string | null>(null);
  const ins = useQuery({ queryKey: ["insights", repoId], queryFn: () => api.insights(repoId) });
  const g = useQuery({ queryKey: ["system-graph", repoId], queryFn: () => api.graphSystem(repoId) });
  // default start: the first API route's handler, else a function in an entry file, else the most-called function
  useEffect(() => {
    if (sid || !g.data || !ins.data) return;
    const syms = g.data.symbols;
    const r = ins.data.routes[0];
    const route = r ? syms.find((s) => s.file === r.file && s.name === r.handler.split(".").pop()) : undefined;
    const entry = g.data.files.find((f) => f.entry);
    const inEntry = entry ? syms.find((s) => s.file === entry.id && /^(main|app|run|start|create_app|index|App)$/i.test(s.name)) ?? syms.find((s) => s.file === entry.id) : undefined;
    const hub = ins.data.hubs[0]?.id;
    setSid(route?.id ?? inEntry?.id ?? hub ?? syms[0]?.id ?? null);
  }, [g.data, ins.data, sid]);
  const flow = useQuery({ queryKey: ["flow", repoId, sid, depth], queryFn: () => api.flow(repoId, sid!, depth), enabled: !!sid });
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-3 py-2">
        <StartPicker repoId={repoId} value={sid} onPick={setSid} />
        <Select aria-label="Depth" className="h-8 w-28 text-xs" value={String(depth)} onValueChange={(v) => setDepth(Number(v))} options={[1, 2, 3, 4, 5].map((d) => ({ value: String(d), label: `Depth ${d}` }))} />
        <Segmented size="sm" value={view} onChange={setView} options={[{ value: "sequence", label: "Sequence diagram", icon: <Workflow /> }, { value: "chart", label: "Flowchart", icon: <ListTree /> }]} />
        {flow.data && <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground"><RouteIcon className="size-3.5" />{flow.data.root.qualname} · {flow.data.steps.length} steps</span>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto bg-surface/30">
        {!sid ? (g.isLoading || ins.isLoading ? <div className="p-10"><Skeleton className="h-72" /></div> : <EmptyState className="h-full" icon={<Workflow className="size-5" />} title="Pick where to start" description="Open the list above and choose an API route, an entry point or any function. The diagram shows what it calls, in source order." />)
          : flow.isLoading ? <div className="p-10"><Skeleton className="h-72" /></div> : flow.isError ? <div className="p-8"><ErrorState error={flow.error} onRetry={() => flow.refetch()} /></div>
          : flow.data && flow.data.steps.length === 0 ? <EmptyState className="h-full" title={`${flow.data.root.qualname} calls nothing the parser could follow`} description="It may only use built-in functions, or call things dynamically. Try another starting point from the list." />
          : flow.data ? (view === "sequence" ? <Sequence flow={flow.data} /> : <Chart flow={flow.data} />) : null}
      </div>
      <p className="shrink-0 border-t px-4 py-1.5 text-[11px] text-muted-foreground">Built from the parser: calls in source order, plus React components a function renders (<code>&lt;Header /&gt;</code>). Solid arrows are resolved; dashed are inferred or unresolved (library or dynamic calls). Click a step to open its code.</p>
    </div>
  );
}
