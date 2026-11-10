"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import ReactFlow, { Background, BackgroundVariant, Controls, MiniMap, ReactFlowProvider, useReactFlow } from "reactflow";
import "reactflow/dist/style.css";
import { ArrowRight, Boxes, ChevronsDownUp, ChevronsUpDown, Crosshair, ExternalLink, FileCode2, Filter, Maximize, Network, Route as RouteIcon, Search, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useCallGraph, useImpact, useModuleGraph, useStats, useTree } from "@/hooks/queries";
import { useTheme } from "@/lib/theme";
import { useOpenFile } from "@/hooks/useOpen";
import { useMedia } from "@/hooks/useMedia";
import { basename, cn, fuzzy } from "@/lib/utils";
import type { Graph, GraphNode } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Drawer } from "@/components/ui/dialog";
import { buildFlow, colorOf, edgeTypes, groupOf, nodeTypes, topDir, type ArchData } from "./flow";

type View = "modules" | "calls" | "impact";
const SOURCE_EXT = /\.(py|js|jsx|ts|tsx|java|go|rs|c|cc|cpp|h|hpp)$/;

function useExpanded(repoId: string, base: Graph | undefined, expanded: Set<string>) {
  const tree = useTree(repoId);
  const key = [...expanded].sort().join("|");
  const subs = useQuery({
    queryKey: ["arch-expand", repoId, key],
    enabled: expanded.size > 0 && !!tree.data,
    queryFn: async () => {
      const out: Graph[] = [];
      for (const dir of expanded) {
        const files = (tree.data ?? []).filter((f) => groupOf(f) === dir && SOURCE_EXT.test(f)).slice(0, 24);
        out.push(...await Promise.all(files.map((f) => api.graphModules(repoId, f, 1, "both"))));
      }
      return out;
    },
  });
  const graph = useMemo<Graph | undefined>(() => {
    if (!base) return undefined;
    if (!base.collapsed || expanded.size === 0) return base;
    const nodeFor = (file: string) => (expanded.has(groupOf(file)) ? file : groupOf(file));
    const nodes = new Map<string, GraphNode>(base.nodes.filter((n) => !expanded.has(n.id)).map((n) => [n.id, n]));
    const edges = new Map<string, { source: string; target: string; weight?: number }>(base.edges.filter((e) => !expanded.has(e.source) && !expanded.has(e.target)).map((e) => [`${e.source}>${e.target}`, e]));
    for (const g of subs.data ?? []) {
      for (const n of g.nodes) if (expanded.has(groupOf(n.file)) && n.kind !== "directory") nodes.set(n.id, { ...n, level: 0 });
      for (const e of g.edges) {
        const s = nodeFor(e.source), t = nodeFor(e.target);
        if (s === t || (!nodes.has(s) && !base.nodes.some((b) => b.id === s)) || (!nodes.has(t) && !base.nodes.some((b) => b.id === t))) continue;
        edges.set(`${s}>${t}`, { source: s, target: t, weight: 1 });
      }
    }
    return { collapsed: true, nodes: [...nodes.values()], edges: [...edges.values()] };
  }, [base, expanded, subs.data]);
  return { graph, loading: subs.isFetching };
}

function Canvas({ repoId, fixedView, introTab }: { repoId: string; fixedView?: View; introTab?: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const openFile = useOpenFile();
  const theme = useTheme((s) => s.theme);
  const rf = useReactFlow();
  const wide = useMedia("(min-width: 1024px)");
  const stats = useStats(repoId);
  const tree = useTree(repoId);

  const [view, setView] = useState<View>(fixedView ?? ((params.get("view") as View) || "modules"));
  const [file, setFile] = useState<string | undefined>(params.get("file") ?? undefined);
  const [symbol, setSymbol] = useState<string | undefined>(params.get("symbol") ?? undefined);
  const [depth, setDepth] = useState(2);
  const [direction, setDirection] = useState("both");
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [hiddenGroups, setHiddenGroups] = useState<Set<string>>(new Set());
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [colorBy, setColorBy] = useState<"folder" | "kind">("folder");
  const [panel, setPanel] = useState(false);
  const [pick, setPick] = useState("");

  const mod = useModuleGraph(repoId, view === "impact" ? file : file, view === "impact" ? 3 : depth, view === "impact" ? "imported_by" : direction, view !== "calls" && (view === "modules" || !!file));
  const calls = useCallGraph(repoId, view === "calls" ? symbol : undefined, depth, direction === "imports" ? "callees" : direction === "imported_by" ? "callers" : "both");
  const impact = useImpact(repoId, view === "impact" ? file : undefined);
  const base = view === "calls" ? calls.data : view === "impact" && !file ? undefined : mod.data;
  const { graph, loading: expanding } = useExpanded(repoId, view === "modules" && !file ? base : undefined, expanded);
  const data = (view === "modules" && !file ? graph : base);
  const isLoading = (view === "calls" ? calls.isFetching && !calls.data : mod.isFetching && !mod.data) ;
  const error = (view === "calls" ? calls.error : mod.error) as Error | null;
  const testFiles = useMemo(() => new Set(impact.data?.tests ?? []), [impact.data]);
  const focusId = view === "calls" ? symbol : file;
  const layout = (view === "modules" && !file) ? "dag" : "layered";

  const flow = useMemo(() => data ? buildFlow({ graph: data, layout, focusId, selected, query, hiddenGroups, hiddenKinds, theme, testFiles, colorBy }) : null, [data, layout, focusId, selected, query, hiddenGroups, hiddenKinds, theme, testFiles, colorBy]);
  const fitKey = `${view}|${file}|${symbol}|${depth}|${direction}|${expanded.size}|${data?.nodes.length}`;
  useEffect(() => { const t = window.setTimeout(() => rf.fitView({ padding: 0.2, duration: 350 }), 60); return () => window.clearTimeout(t); }, [fitKey, rf]);
  useEffect(() => { setSelected(null); }, [view, file, symbol]);

  const groups = useMemo(() => { const m = new Map<string, number>(); for (const n of data?.nodes ?? []) { const k = n.kind === "directory" ? n.name : topDir(n.file); m.set(k, (m.get(k) ?? 0) + (n.count ?? 1)); } return [...m.entries()].sort((a, b) => b[1] - a[1]); }, [data]);
  const kinds = useMemo(() => [...new Set((data?.nodes ?? []).map((n) => n.kind ?? "file"))], [data]);
  const sel = selected ? data?.nodes.find((n) => n.id === selected) : undefined;

  const focusFile = (f: string, v: View = "modules") => { setView(v); setFile(f); setSymbol(undefined); setSelected(null); setDepth(v === "impact" ? 3 : 1); };
  const focusSymbol = (id: string) => { setView("calls"); setSymbol(id); setFile(undefined); setDepth(2); };
  const reset = () => { setFile(undefined); setSymbol(undefined); setHiddenGroups(new Set()); setHiddenKinds(new Set()); setExpanded(new Set()); setQuery(""); setView("modules"); router.replace("/architecture"); };
  const toggle = (s: Set<string>, v: string) => { const n = new Set(s); if (n.has(v)) n.delete(v); else n.add(v); return n; };
  const matches = flow?.nodes.filter((n) => n.data.match) ?? [];
  const goMatches = () => { if (matches.length) { rf.fitView({ nodes: matches.map((m) => ({ id: m.id })), padding: 0.5, duration: 400, maxZoom: 1.4 }); setSelected(matches[0].id); } };

  const results = useQuery({
    queryKey: ["arch-pick", repoId, view, pick],
    enabled: pick.trim().length >= 2,
    queryFn: async () => view === "calls" ? { kind: "symbol" as const, items: (await api.symbols(repoId, { q: pick })).slice(0, 10) } : { kind: "file" as const, items: [] as never[] },
  });
  const fileHits = useMemo(() => view === "calls" || pick.trim().length < 2 ? [] : (tree.data ?? []).filter((f) => SOURCE_EXT.test(f)).map((f) => ({ f, s: Math.max(fuzzy(pick, basename(f)) + 2, fuzzy(pick, f)) })).filter((x) => x.s >= 0).sort((a, b) => b.s - a.s).slice(0, 10).map((x) => x.f), [view, pick, tree.data]);

  const routes = stats.data?.apis.items ?? [];
  const openHandler = async (r: (typeof routes)[number]) => {
    try {
      const name = r.handler.split(".").pop() ?? r.handler;
      const hit = (await api.symbols(repoId, { q: name })).find((s) => s.file === r.file && (s.name === name || s.qualname === r.handler)) ?? (await api.symbols(repoId, { q: name }))[0];
      if (!hit) { toast.message("That handler isn’t in the symbol index"); return; }
      focusSymbol(hit.id);
    } catch (e) { toast.error((e as Error).message); }
  };

  const side = (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-3 border-b p-3">
        {!fixedView && <Segmented value={view} onChange={(v) => { setView(v); setSelected(null); if (v === "calls") setFile(undefined); else setSymbol(undefined); }} className="w-full [&>button]:flex-1"
          options={[{ value: "modules", label: "Modules", icon: <Network /> }, { value: "calls", label: "Calls", icon: <ArrowRight /> }, { value: "impact", label: "Impact", icon: <Sparkles /> }]} />}
        <p className="text-xs leading-relaxed text-muted-foreground">{view === "modules" ? "How files import each other. Pick a file to focus the graph on it." : view === "calls" ? "Who calls a function and what it calls. Pick a function." : "Everything that depends on a file, and the tests that exercise it."}</p>
        <div className="relative"><Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" /><Input value={pick} onChange={(e) => setPick(e.target.value)} placeholder={view === "calls" ? "Find a function or class…" : "Find a file to focus…"} aria-label="Pick what to focus on" className="pl-8" /></div>
        {(fileHits.length > 0 || (results.data?.items.length ?? 0) > 0) && (
          <ul className="max-h-48 overflow-y-auto rounded-lg border bg-panel p-1">
            {fileHits.map((f) => <li key={f}><button onClick={() => { focusFile(f, view); setPick(""); }} className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[13px] hover:bg-accent"><FileCode2 className="size-3.5 text-muted-foreground" /><span className="truncate">{f}</span></button></li>)}
            {results.data?.kind === "symbol" && results.data.items.map((s) => <li key={s.id}><button onClick={() => { focusSymbol(s.id); setPick(""); }} className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[13px] hover:bg-accent"><span className="truncate">{s.qualname}</span><span className="ml-auto truncate font-mono text-[11px] text-muted-foreground">{s.file}</span></button></li>)}
          </ul>
        )}
        {(file || symbol) && <div className="flex items-center gap-2 rounded-lg bg-primary/8 px-2.5 py-1.5 text-xs"><Crosshair className="size-3.5 shrink-0 text-primary" /><span className="min-w-0 flex-1 truncate font-mono">{file ?? data?.nodes.find((n) => n.id === symbol)?.qualname ?? symbol}</span><button onClick={reset} aria-label="Clear focus" className="text-muted-foreground hover:text-foreground"><X className="size-3.5" /></button></div>}
        {(file || symbol) && view !== "impact" && (
          <div className="flex gap-2">
            <Select aria-label="Direction" className="h-7 flex-1 text-xs" value={direction} onValueChange={setDirection} options={view === "calls" ? [{ value: "both", label: "Callers + callees" }, { value: "imported_by", label: "Callers only" }, { value: "imports", label: "Callees only" }] : [{ value: "both", label: "Imports + imported by" }, { value: "imports", label: "Imports" }, { value: "imported_by", label: "Imported by" }]} />
            <Select aria-label="Depth" className="h-7 w-24 text-xs" value={String(depth)} onValueChange={(v) => setDepth(Number(v))} options={[1, 2, 3, 4].map((d) => ({ value: String(d), label: `Depth ${d}` }))} />
          </div>
        )}
      </div>
      <Tabs defaultValue={introTab ?? "filter"} className="flex min-h-0 flex-1 flex-col">
        <TabsList className="shrink-0 border-b px-2 pt-1"><TabsTrigger value="filter"><Filter className="size-3.5" />Filters</TabsTrigger><TabsTrigger value="routes"><RouteIcon className="size-3.5" />Routes {routes.length > 0 && <span className="tabular-nums text-muted-foreground">{routes.length}</span>}</TabsTrigger><TabsTrigger value="models"><Boxes className="size-3.5" />Models</TabsTrigger></TabsList>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <TabsContent value="filter" className="space-y-4">
            <div><div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Colour by</div><Segmented size="sm" value={colorBy} onChange={setColorBy} options={[{ value: "folder", label: "Folder" }, { value: "kind", label: "Kind" }]} /></div>
            <div><div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Folders</div>
              {groups.length === 0 ? <p className="text-xs text-muted-foreground">No graph loaded.</p> : <ul className="space-y-0.5">{groups.map(([g, n]) => <li key={g}><label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-[13px] hover:bg-accent/60"><input type="checkbox" className="accent-[hsl(var(--primary))]" checked={!hiddenGroups.has(g)} onChange={() => setHiddenGroups((s) => toggle(s, g))} /><span className="size-2 rounded-sm" style={{ background: colorOf(g.split("/")[0]) }} /><span className="truncate">{g}</span><span className="ml-auto tabular-nums text-xs text-muted-foreground">{n}</span></label></li>)}</ul>}</div>
            {kinds.length > 1 && <div><div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Kinds</div><div className="flex flex-wrap gap-1.5">{kinds.map((k) => <button key={k} onClick={() => setHiddenKinds((s) => toggle(s, k))} aria-pressed={!hiddenKinds.has(k)} className={cn("rounded-md border px-2 py-0.5 text-xs capitalize", hiddenKinds.has(k) ? "text-muted-foreground line-through" : "bg-accent")}>{k}</button>)}</div></div>}
            {expanded.size > 0 && <div><div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Expanded folders</div><div className="flex flex-wrap gap-1.5">{[...expanded].map((d) => <button key={d} onClick={() => setExpanded((s) => toggle(s, d))} className="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-0.5 text-xs"><ChevronsDownUp className="size-3" />{d}</button>)}</div></div>}
            <div className="rounded-lg bg-surface p-2.5 text-[11px] leading-relaxed text-muted-foreground"><div className="mb-1 font-medium text-foreground">Legend</div><span className="text-[#0369a1] dark:text-[#7dd3fc]">━</span> outgoing (selected node uses) · <span className="text-[#b45309] dark:text-[#fcd34d]">━</span> incoming (uses selected node) · dashed = guessed by name · green border = test file</div>
          </TabsContent>
          <TabsContent value="routes">{routes.length === 0 ? <EmptyState className="py-8" title="No API routes detected" /> : <ul className="space-y-1">{routes.slice(0, 80).map((r, i) => <li key={i}><button onClick={() => void openHandler(r)} className="w-full rounded-md px-2 py-1.5 text-left hover:bg-accent/60"><div className="flex items-center gap-2 text-[13px]"><Badge variant="info" className="font-mono">{r.method}</Badge><span className="truncate font-mono">{r.path}</span></div><div className="mt-0.5 truncate text-[11px] text-muted-foreground">{r.handler} · {r.file}:{r.line}</div></button></li>)}</ul>}</TabsContent>
          <TabsContent value="models">{(stats.data?.models.length ?? 0) === 0 ? <EmptyState className="py-8" title="No data models detected" /> : <ul className="space-y-1">{stats.data!.models.map((m) => <li key={m.name + m.file}><button onClick={() => focusFile(m.file)} className="w-full rounded-md px-2 py-1.5 text-left hover:bg-accent/60"><div className="text-[13px] font-medium">{m.name}</div><div className="truncate text-[11px] text-muted-foreground">{m.framework} · {m.fields} fields · {m.file}:{m.line}</div></button></li>)}</ul>}</TabsContent>
        </div>
      </Tabs>
    </div>
  );

  const details = sel && (
    <div className="absolute right-3 top-3 z-10 w-72 rounded-xl bg-panel p-3.5 shadow-pop" role="dialog" aria-label="Node details">
      <div className="flex items-start gap-2"><div className="min-w-0 flex-1"><div className="truncate text-[13px] font-semibold">{sel.qualname ?? sel.name}</div><div className="truncate font-mono text-[11px] text-muted-foreground">{sel.file}{sel.start ? `:${sel.start}` : ""}</div></div><button onClick={() => setSelected(null)} aria-label="Close details" className="text-muted-foreground hover:text-foreground"><X className="size-4" /></button></div>
      <div className="mt-2 flex flex-wrap gap-1.5">{sel.kind && <Badge variant="secondary" className="capitalize">{sel.kind}</Badge>}{sel.language && <Badge variant="outline">{sel.language}</Badge>}{sel.route && <Badge variant="info">{sel.route}</Badge>}{sel.symbols != null && <Badge variant="outline">{sel.symbols} symbols</Badge>}{sel.count && sel.count > 1 && <Badge variant="outline">{sel.count} files</Badge>}</div>
      {sel.signature && <code className="mt-2 block break-words font-mono text-[11px] text-muted-foreground">{sel.signature}</code>}
      {sel.external && sel.external.length > 0 && <div className="mt-2 text-[11px] text-muted-foreground">External imports: {sel.external.slice(0, 8).join(", ")}</div>}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {sel.kind === "directory" ? <Button size="xs" onClick={() => setExpanded((s) => toggle(s, sel.id))} loading={expanding}><ChevronsUpDown />Expand folder</Button> : <Button size="xs" onClick={() => openFile(sel.file, sel.start, sel.end)}><ExternalLink />Open code</Button>}
        {sel.kind !== "directory" && (view === "calls" ? <Button size="xs" variant="outline" onClick={() => focusSymbol(sel.id)}><Crosshair />Focus here</Button> : <><Button size="xs" variant="outline" onClick={() => focusFile(sel.file, "modules")}><Crosshair />Focus</Button><Button size="xs" variant="outline" onClick={() => focusFile(sel.file, "impact")}><Sparkles />Impact</Button></>)}
      </div>
    </div>
  );

  return (
    <div className="flex h-full min-h-0">
      {wide && <aside className="w-72 shrink-0 border-r bg-panel" aria-label="Graph controls">{side}</aside>}
      <div className="relative min-w-0 flex-1">
        <div className="absolute left-3 top-3 z-10 flex items-center gap-2">
          {!wide && <Button size="sm" variant="outline" onClick={() => setPanel(true)}><Filter />Controls</Button>}
          <div className="relative"><Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" /><Input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && goMatches()} placeholder="Search nodes…" aria-label="Search nodes in the graph" className="h-8 w-52 bg-panel pl-8 shadow-card" /></div>
          {query && <Badge variant={matches.length ? "warning" : "secondary"}>{matches.length} match{matches.length === 1 ? "" : "es"}</Badge>}
          <Button size="icon" variant="outline" onClick={() => rf.fitView({ padding: 0.2, duration: 300 })} aria-label="Fit graph to view"><Maximize /></Button>
        </div>
        {error ? <div className="flex h-full items-center justify-center p-8"><ErrorState title="Couldn’t load the graph" error={error} onRetry={() => (view === "calls" ? calls.refetch() : mod.refetch())} /></div>
          : (view === "calls" && !symbol) ? <div className="flex h-full items-center justify-center"><EmptyState icon={<ArrowRight className="size-5" />} title="Choose a function to trace" description="Search for a function or class on the left, or pick an API route from the Routes tab, to see its callers and callees." /></div>
          : (view === "impact" && !file) ? <div className="flex h-full items-center justify-center"><EmptyState icon={<Sparkles className="size-5" />} title="Choose a file to analyse" description="See every file that depends on it, directly or indirectly, and the tests that exercise it. Search for a file on the left." /></div>
          : isLoading && !flow ? <div className="p-16"><Skeleton className="h-80" /></div>
          : flow && flow.nodes.length === 0 ? <div className="flex h-full items-center justify-center"><EmptyState icon={<Network className="size-5" />} title="Nothing to show" description={flow.hidden ? "All nodes are hidden by the filters." : "This graph has no nodes. The language may not be parsed, or the file has no imports."} /></div>
          : (
            <ReactFlow nodes={flow?.nodes ?? []} edges={flow?.edges ?? []} nodeTypes={nodeTypes} edgeTypes={edgeTypes} minZoom={0.08} maxZoom={2.2} nodesConnectable={false} proOptions={{ hideAttribution: true }}
              onNodeClick={(_, n) => setSelected((cur) => (cur === n.id ? null : n.id))} onNodeDoubleClick={(_, n) => { const d = n.data as ArchData; if (d.kind === "directory") setExpanded((s) => toggle(s, n.id)); else openFile(d.raw.file, d.raw.start, d.raw.end); }} onPaneClick={() => setSelected(null)}>
              <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color={theme === "dark" ? "#2a2d36" : "#d4d8e0"} />
              <Controls showInteractive={false} />
              <MiniMap pannable zoomable nodeStrokeWidth={2} nodeColor={(n) => (n.data as ArchData).color.startsWith("hsl") ? "#818cf8" : (n.data as ArchData).color} maskColor={theme === "dark" ? "rgba(0,0,0,.55)" : "rgba(255,255,255,.6)"} />
            </ReactFlow>
          )}
        {details}
        {flow && flow.nodes.length > 0 && <div className="pointer-events-none absolute bottom-3 left-3 z-10 rounded-md bg-panel/90 px-2.5 py-1 text-[11px] text-muted-foreground shadow-card">{flow.nodes.length} nodes · {flow.edges.length} edges{flow.hidden ? ` · ${flow.hidden} hidden` : ""} · click to highlight dependencies · double-click to open</div>}
      </div>
      {!wide && <Drawer open={panel} onOpenChange={setPanel} title="Graph controls" width="max-w-sm">{side}</Drawer>}
    </div>
  );
}

export function ArchitecturePage({ repoId, fixedView, introTab }: { repoId: string; fixedView?: "modules" | "calls" | "impact"; introTab?: string }) {
  return <ReactFlowProvider><Canvas repoId={repoId} fixedView={fixedView} introTab={introTab} /></ReactFlowProvider>;
}
