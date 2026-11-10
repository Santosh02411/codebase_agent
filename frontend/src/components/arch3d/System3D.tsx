"use client";
import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import * as THREE from "three";
import { Box, Boxes, ChevronLeft, CircleHelp, Filter, Layers, RotateCcw, Search, Sparkles, X } from "lucide-react";
import { api } from "@/lib/api";
import { useTheme } from "@/lib/theme";
import { useMedia } from "@/hooks/useMedia";
import { basename, cn, fuzzy } from "@/lib/utils";
import type { SgEdge, SgEdgeType } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Segmented, Switch } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Dropdown, DropdownContent, DropdownItem, DropdownLabel, DropdownTrigger } from "@/components/ui/dropdown";
import { adjacency, clusterColor, langColor, layoutSystem, symbolPositions, tracePath } from "./layout3d";
import { InfoPanel, type Maps, type Sel, type TraceState } from "./InfoPanel";
import type { E2 } from "./Graph2D";
import type { Fly, Hull, SEdge, SNode } from "./Scene3D";

const Scene3D = dynamic(() => import("./Scene3D"), { ssr: false, loading: () => <div className="p-10"><Skeleton className="h-96" /></div> });
const Graph2D = dynamic(() => import("./Graph2D"), { ssr: false, loading: () => <div className="p-10"><Skeleton className="h-96" /></div> });

const EDGE_COLOR: Record<SgEdgeType, { dark: string; light: string }> = {
  import: { dark: "#8b97b3", light: "#64748b" }, file_call: { dark: "#a78bfa", light: "#7c3aed" }, call: { dark: "#a78bfa", light: "#7c3aed" },
  inherit: { dark: "#34d399", light: "#059669" }, test: { dark: "#2dd4bf", light: "#0d9488" },
};
const BG = { dark: "#0f1014", light: "#f6f7f9" };
const mix = (hex: string, bg: string, k: number) => `#${new THREE.Color(hex).lerp(new THREE.Color(bg), k).getHexString()}`;
const canWebGL = () => { try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch { return false; } };

const ONBOARD_KEY = "codebase-agent-3d-onboarded";

function Legend({ colorBy }: { colorBy: string }) {
  const row = (swatch: React.ReactNode, text: string) => <li className="flex items-center gap-2">{swatch}<span>{text}</span></li>;
  const dot = (cls: string) => <span className={cn("size-2.5 shrink-0", cls)} />;
  const line = (c: string, dashed?: boolean) => <span className="inline-block h-0 w-5 shrink-0 border-t-2" style={{ borderColor: c, borderStyle: dashed ? "dashed" : "solid" }} />;
  return (
    <div className="pointer-events-auto w-60 rounded-xl bg-panel/95 p-3 text-[11.5px] shadow-pop backdrop-blur">
      <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Legend</div>
      <ul className="space-y-1">
        {row(dot("rotate-45 rounded-sm bg-primary"), "Folder (cluster core). Click to enter")}
        {row(dot("rounded-full bg-info"), "Source file")}
        {row(dot("rounded-[2px] bg-success"), "Test file")}
        {row(dot("rotate-45 bg-warning"), "Entry point or route")}
        {row(dot("rounded-full bg-chart-6 !size-1.5"), "Function / class (appears when you select or enter)")}
      </ul>
      <div className="my-2 border-t" />
      <ul className="space-y-1">
        {row(line("#8b97b3"), "Imports (verified)")}{row(line("#a78bfa"), "Calls (verified)")}{row(line("#34d399"), "Inheritance (verified)")}{row(line("#2dd4bf"), "Test covers module")}
        {row(line("#a78bfa", true), "Dashed = inferred (a guess)")}
        {row(line("#38bdf8"), "Selected node uses (outgoing)")}{row(line("#fbbf24"), "Uses the selected node (incoming)")}{row(line("#4ade80"), "Traced path")}
      </ul>
      <p className="mt-2 leading-relaxed text-muted-foreground">Verified = resolved by the parser from your code. Inferred = matched by name only. Colour: {colorBy}.</p>
    </div>
  );
}

function Onboarding({ onClose }: { onClose: () => void }) {
  const steps = [["Drag", "to rotate. Scroll to zoom. Right-drag (or Shift+drag) to pan."], ["Click a folder core", "to enter it: its files and functions come into focus and the rest fades."], ["Click a file or function", "to inspect it. Blue lines are what it uses, amber lines are what uses it, and the moving dots show the direction."], ["Trace path…", "finds how one file or function reaches another through real imports and calls."], ["Dashed lines", "are inferred (matched by name). Solid lines were verified by the parser."]];
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/70 p-4 backdrop-blur-sm" role="dialog" aria-label="How to use the 3D explorer">
      <div className="w-full max-w-md rounded-2xl bg-panel p-5 shadow-pop">
        <div className="flex items-center gap-2 text-sm font-semibold"><Box className="size-4 text-primary" />Your repository, as a map</div>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">Every node and line here comes from the parsed code of this project. Nothing is decorative.</p>
        <ul className="mt-3 space-y-2 text-[13px]">{steps.map(([a, b]) => <li key={a}><span className="font-medium">{a}</span> <span className="text-muted-foreground">{b}</span></li>)}</ul>
        <div className="mt-4 flex justify-end"><Button size="sm" onClick={onClose}>Got it</Button></div>
      </div>
    </div>
  );
}

export function System3D({ repoId, className }: { repoId: string; className?: string }) {
  const theme = useTheme((s) => s.theme);
  const osReduced = useMedia("(prefers-reduced-motion: reduce)", false);
  const [reduceMotion, setReduceMotion] = useState(false);
  const reduced = osReduced || reduceMotion;
  const [webgl, setWebgl] = useState<boolean | null>(null);
  const [mode, setMode] = useState<"3d" | "2d">("3d");
  const [colorBy, setColorBy] = useState<"folder" | "language" | "kind">("folder");
  const [types, setTypes] = useState({ folders: true, files: true, tests: true, symbols: true });
  const [rels, setRels] = useState({ import: true, call: true, inherit: true, test: true });
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [allSymbols, setAllSymbols] = useState(false);
  const [sel, setSel] = useState<Sel | null>(null);
  const [hover, setHover] = useState<SNode | null>(null);
  const [focusCluster, setFocusCluster] = useState<string | null>(null);
  const [fly, setFly] = useState<Fly | null>(null);
  const [q, setQ] = useState("");
  const [legend, setLegend] = useState(true);
  const [onboard, setOnboard] = useState(false);
  const [trace, setTrace] = useState<TraceState>({ from: null, to: null, undirected: false, path: null, picking: false });

  useEffect(() => { setWebgl(canWebGL()); try { setOnboard(!localStorage.getItem(ONBOARD_KEY)); } catch { /* storage unavailable */ } }, []);
  useEffect(() => { if (webgl === false || osReduced) setMode("2d"); }, [webgl, osReduced]);

  const gq = useQuery({ queryKey: ["system-graph", repoId], queryFn: () => api.graphSystem(repoId) });
  const graph = gq.data;
  const layout = useMemo(() => (graph ? layoutSystem(graph) : null), [graph]);
  const adj = useMemo(() => adjacency(graph?.edges ?? []), [graph]);
  const clusterIdx = useMemo(() => new Map((layout?.clusters ?? []).map((c, i) => [c.id, i])), [layout]);
  const extent = useMemo(() => { let m = 10; (layout?.clusters ?? []).forEach((c) => { m = Math.max(m, Math.hypot(c.x, c.y, c.z) + c.radius); }); return m; }, [layout]);
  const startDistance = extent * 2.4 + 8;
  useEffect(() => { if (layout) setFly({ x: 0, y: 0, z: 0, dist: startDistance, nonce: Date.now() }); }, [layout, startDistance]);

  // which files show their functions
  const symbolFiles = useMemo(() => {
    const s = new Set<string>();
    if (!layout || !types.symbols) return s;
    if (allSymbols) { [...layout.symbolsByFile.keys()].slice(0, 80).forEach((f) => s.add(f)); }
    if (focusCluster) layout.clusters.find((c) => c.id === focusCluster)?.files.slice(0, 60).forEach((f) => s.add(f));
    if (sel?.kind === "file") s.add(sel.id);
    if (sel?.kind === "symbol") { const f = graph?.symbols.find((x) => x.id === sel.id)?.file; if (f) s.add(f); }
    return s;
  }, [layout, types.symbols, allSymbols, focusCluster, sel, graph]);
  const syms = useMemo(() => (layout ? symbolPositions(layout, symbolFiles) : new Map()), [layout, symbolFiles]);

  const allowEdge = (e: SgEdge) => {
    if (verifiedOnly && !e.verified) return false;
    if (e.type === "import") return rels.import; if (e.type === "test") return rels.test && types.tests;
    if (e.type === "file_call") return rels.call; if (e.type === "call") return rels.call; return rels.inherit;
  };
  const maps: Maps = useMemo(() => ({
    label: (id) => layout?.clusters.find((c) => c.id === id)?.label ?? (layout?.files.has(id) ? basename(id) : graph?.symbols.find((s) => s.id === id)?.qualname ?? id),
    kindOf: (id) => (layout?.clusters.some((c) => c.id === id) ? "cluster" : layout?.files.has(id) ? "file" : graph?.symbols.some((s) => s.id === id) ? "symbol" : undefined),
  }), [layout, graph]);

  const scene = useMemo(() => {
    if (!graph || !layout) return null;
    const bg = BG[theme];
    const nodes: SNode[] = []; const pos = new Map<string, [number, number, number]>(); const nid = new Map<string, SNode>();
    const selIsCluster = sel?.kind === "cluster" ? sel.id : null;
    const fileOf = (id: string) => (layout.files.has(id) ? id : graph.symbols.find((s) => s.id === id)?.file ?? id);
    // neighbours of the selection, from the edges that will be drawn
    const hiOut = new Set<string>(), hiIn = new Set<string>();
    const visibleEdges = graph.edges.filter(allowEdge);
    const selFiles = selIsCluster ? new Set(layout.clusters.find((c) => c.id === selIsCluster)?.files ?? []) : null;
    for (const e of visibleEdges) {
      if (!sel) break;
      const sFile = fileOf(e.source), tFile = fileOf(e.target);
      if (sel.kind === "cluster") { const sIn = selFiles!.has(sFile), tIn = selFiles!.has(tFile); if (sIn && !tIn) hiOut.add(e.target); if (tIn && !sIn) hiIn.add(e.source); }
      else if (sel.kind === "file" && (e.type === "import" || e.type === "test" || e.type === "file_call")) { if (e.source === sel.id) hiOut.add(e.target); if (e.target === sel.id) hiIn.add(e.source); }
      else if (sel.kind === "file") { if (sFile === sel.id) hiOut.add(e.target); if (tFile === sel.id) hiIn.add(e.source); }
      else if (e.source === sel.id) hiOut.add(e.target); else if (e.target === sel.id) hiIn.add(e.source);
    }
    const pathNodes = new Set<string>(); (trace.path ?? []).forEach((e) => { pathNodes.add(e.source); pathNodes.add(e.target); });
    const near = (id: string) => hiOut.has(id) || hiIn.has(id) || pathNodes.has(id);
    const inFocus = (cluster: string) => !focusCluster || focusCluster === cluster;
    const dimmed = (id: string, cluster: string) => (sel ? !(id === sel.id || near(id) || (sel.kind === "cluster" && cluster === sel.id)) : !inFocus(cluster));
    const colorOf = (c: string, base: string, kindColor: string, lang: string) => (colorBy === "folder" ? clusterColor(clusterIdx.get(c) ?? 0) : colorBy === "language" ? langColor(lang) : kindColor) || base;
    const add = (n: SNode, dim: boolean) => { const c = dim ? mix(n.color, bg, 0.82) : n.color; const x = { ...n, color: c }; nodes.push(x); nid.set(n.id, x); pos.set(n.id, [n.x, n.y, n.z]); };
    if (types.folders) layout.clusters.forEach((c, i) => add({ id: c.id, kind: "cluster", x: c.x, y: c.y, z: c.z, r: 0.5 + Math.cbrt(c.files.length) * 0.2, color: clusterColor(i), shape: "core", label: c.label, sub: `${c.files.length}`, emphasis: sel?.id === c.id ? 2 : 0 }, sel ? !(sel.id === c.id || near(c.id)) && sel.kind !== "cluster" ? true : (sel.kind === "cluster" && sel.id !== c.id && !near(c.id)) : !inFocus(c.id)));
    else layout.clusters.forEach((c) => pos.set(c.id, [c.x, c.y, c.z]));
    for (const f of layout.files.values()) {
      if ((f.file.is_test && !types.tests) || !types.files) { pos.set(f.id, [f.x, f.y, f.z]); continue; }
      const kind = f.file.is_test ? "#2dd4bf" : f.file.entry ? "#f59e0b" : "#38bdf8";
      add({ id: f.id, kind: "file", x: f.x, y: f.y, z: f.z, r: f.r, color: f.file.entry && colorBy !== "kind" ? "#f59e0b" : colorOf(f.cluster, kind, kind, f.file.language), shape: f.file.is_test ? "box" : f.file.entry ? "octa" : "sphere", label: basename(f.id), emphasis: sel?.id === f.id ? 2 : near(f.id) ? 1 : 0, sub: f.file.entry ? "entry" : undefined }, dimmed(f.id, f.cluster));
    }
    if (types.symbols) for (const s of syms.values()) {
      const cl = layout.clusterOf.get(s.sym.file) ?? "";
      const kc = s.sym.route ? "#f59e0b" : s.sym.kind === "class" ? "#c084fc" : "#a5b4fc";
      add({ id: s.id, kind: "symbol", x: s.x, y: s.y, z: s.z, r: s.r, color: s.sym.route ? "#f59e0b" : colorBy === "folder" ? kc : colorBy === "language" ? langColor(layout.files.get(s.sym.file)?.file.language ?? "") : kc, shape: s.sym.route ? "octa" : s.sym.kind === "class" ? "box" : "sphere", label: s.sym.qualname, emphasis: sel?.id === s.id ? 2 : near(s.id) ? 1 : 0 }, dimmed(s.id, cl));
    }
    const P = (id: string): [number, number, number] | undefined => pos.get(id) ?? pos.get(fileOf(id));
    const edges: (SEdge & { s: string; t: string })[] = [];
    const pathKeys = new Set((trace.path ?? []).map((e) => `${e.type}|${e.source}|${e.target}`));
    for (const e of visibleEdges) {
      const sShown = nid.has(e.source), tShown = nid.has(e.target);
      if (e.type === "call" || e.type === "inherit") { if (!sShown || !tShown) continue; }
      else if (!sShown || !tShown) continue;
      const a = P(e.source), b = P(e.target); if (!a || !b) continue;
      const onPath = pathKeys.has(`${e.type}|${e.source}|${e.target}`);
      let hi: SEdge["hi"] = onPath ? "path" : null;
      if (!hi && sel) {
        const sFile = fileOf(e.source), tFile = fileOf(e.target);
        if (sel.kind === "cluster") { const sIn = selFiles!.has(sFile), tIn = selFiles!.has(tFile); hi = sIn && !tIn ? "out" : tIn && !sIn ? "in" : null; }
        else if (sel.kind === "file") hi = (e.type === "call" || e.type === "inherit" ? sFile === sel.id : e.source === sel.id) ? "out" : (e.type === "call" || e.type === "inherit" ? tFile === sel.id : e.target === sel.id) ? "in" : null;
        else hi = e.source === sel.id ? "out" : e.target === sel.id ? "in" : null;
      }
      const base = EDGE_COLOR[e.type][theme];
      const faded = (sel || trace.path) && !hi;
      const outside = focusCluster && !(layout.clusterOf.get(fileOf(e.source)) === focusCluster || layout.clusterOf.get(fileOf(e.target)) === focusCluster);
      edges.push({ a, b, color: faded || outside ? mix(base, bg, 0.88) : base, dashed: !e.verified, hi, key: `${e.type}|${e.source}|${e.target}`, s: e.source, t: e.target });
    }
    const hulls: Hull[] = layout.clusters.map((c, i) => ({ id: c.id, x: c.x, y: c.y, z: c.z, radius: c.radius, color: clusterColor(i), active: focusCluster === c.id || sel?.id === c.id, label: c.label, files: c.files.length }));
    const labelIds = new Set<string>();
    if (hover) labelIds.add(hover.id);
    if (sel) { labelIds.add(sel.id); [...hiOut, ...hiIn].slice(0, 10).forEach((i) => labelIds.add(i)); }
    pathNodes.forEach((i) => labelIds.add(i));
    if (focusCluster) layout.clusters.find((c) => c.id === focusCluster)?.files.slice(0, 14).forEach((f) => labelIds.add(f));
    if (layout.clusters.length <= 30 && types.folders) layout.clusters.forEach((c) => labelIds.add(c.id));
    const labels = [...labelIds].map((id) => nid.get(id)).filter(Boolean) as SNode[];
    return { nodes, edges, hulls, labels };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, layout, syms, sel, hover, focusCluster, theme, colorBy, types, rels, verifiedOnly, trace.path, clusterIdx]);

  const flyTo = (id: string, dist: number) => {
    const c = layout?.clusters.find((x) => x.id === id); const f = layout?.files.get(id); const s = syms.get(id) ?? (graph?.symbols.find((x) => x.id === id) ? (() => { const ff = layout?.files.get(graph!.symbols.find((x) => x.id === id)!.file); return ff ? { x: ff.x, y: ff.y, z: ff.z } : undefined; })() : undefined);
    const p = c ?? f ?? s; if (p) setFly({ x: p.x, y: p.y, z: p.z, dist, nonce: Date.now() });
  };
  const select = (id: string, fit = true) => {
    const kind = maps.kindOf(id); if (!kind) return;
    setSel({ kind, id });
    if (fit) flyTo(id, kind === "cluster" ? (layout!.clusters.find((c) => c.id === id)!.radius * 3.2) : kind === "file" ? 12 : 9);
  };
  const enter = (id: string) => { setFocusCluster(id); setSel({ kind: "cluster", id }); flyTo(id, (layout!.clusters.find((c) => c.id === id)?.radius ?? 4) * 3.0); };
  const exit = () => { setFocusCluster(null); setFly({ x: 0, y: 0, z: 0, dist: startDistance, nonce: Date.now() }); };
  const pick = (n: SNode) => { if (n.kind === "cluster") { if (focusCluster === n.id) select(n.id); else enter(n.id); } else select(n.id, false); };
  const runTrace = (from: string, to: string, undirected: boolean) => {
    if (!graph) return;
    const kf = maps.kindOf(from), kt = maps.kindOf(to);
    const fileLevel = kf !== "symbol" || kt !== "symbol";
    const norm = (id: string) => (maps.kindOf(id) === "symbol" ? graph.symbols.find((s) => s.id === id)!.file : id);
    const a = fileLevel ? norm(from) : from, b = fileLevel ? norm(to) : to;
    const ok = (e: SgEdge) => allowEdge(e) && (fileLevel ? e.type === "import" || e.type === "test" || e.type === "file_call" : e.type === "call" || e.type === "inherit");
    setTrace({ from, to, undirected, path: tracePath(adj, a, b, ok, undirected), picking: false });
    flyTo(to, 14);
  };

  const results = useMemo(() => {
    if (!graph || q.trim().length < 2) return [];
    const items = [...(layout?.clusters ?? []).map((c) => ({ id: c.id, label: c.label, hint: "folder", s: fuzzy(q, c.label) })), ...graph.files.map((f) => ({ id: f.id, label: basename(f.id), hint: f.id, s: Math.max(fuzzy(q, basename(f.id)) + 2, fuzzy(q, f.id)) })),
      ...graph.symbols.map((s) => ({ id: s.id, label: s.qualname, hint: s.file, s: Math.max(fuzzy(q, s.qualname) + 1, fuzzy(q, s.name)) }))];
    return items.filter((x) => x.s >= 0).sort((a, b) => b.s - a.s).slice(0, 8);
  }, [q, graph, layout]);
  const targets = useMemo(() => [...(graph?.files ?? []).map((f) => ({ id: f.id, label: basename(f.id), hint: f.id })), ...(graph?.symbols ?? []).map((s) => ({ id: s.id, label: s.qualname, hint: s.file }))], [graph]);

  const hoverTip = hover && hover.kind !== "cluster" ? hover : null;
  const closeOnboard = () => { setOnboard(false); try { localStorage.setItem(ONBOARD_KEY, "1"); } catch { /* ignore */ } };
  const reset = () => { setSel(null); setFocusCluster(null); setTrace({ from: null, to: null, undirected: false, path: null, picking: false }); setQ(""); setFly({ x: 0, y: 0, z: 0, dist: startDistance, nonce: Date.now() }); };

  if (gq.isLoading) return <div className="p-10"><Skeleton className="h-[60vh]" /></div>;
  if (gq.isError) return <div className="p-10"><ErrorState title="Couldn’t load the repository graph" error={gq.error} onRetry={() => gq.refetch()} /></div>;
  if (!graph || !layout || graph.files.length === 0) return <EmptyState className="h-full" icon={<Layers className="size-5" />} title="Nothing parsed yet" description="No source files were parsed for this project, so there is no structure to draw. Re-index it, or check that its languages are supported." />;

  const stat = graph.stats;
  return (
    <div className={cn("relative flex h-full min-h-0", className)}>
      <div className="relative min-w-0 flex-1 overflow-hidden bg-[radial-gradient(ellipse_at_center,hsl(var(--surface)),hsl(var(--background))_70%)]">
        <div className="absolute inset-0">
          {mode === "3d" && webgl && scene ? <Scene3D nodes={scene.nodes} edges={scene.edges} hulls={scene.hulls} labels={scene.labels} fly={fly} reduced={reduced} theme={theme} startDistance={startDistance} onPick={pick} onHover={setHover} onEmpty={() => { setSel(null); }} />
            : scene ? <Graph2D nodes={scene.nodes} edges={scene.edges as E2[]} onPick={pick} onEmpty={() => setSel(null)} /> : null}
        </div>

        <div className="pointer-events-none absolute left-3 right-3 top-3 z-10 flex flex-wrap items-start gap-2">
          <div className="pointer-events-auto relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && results[0]) { select(results[0].id); setQ(""); } }} placeholder="Find a folder, file or function…" aria-label="Search the repository graph" className="h-8 w-64 bg-panel pl-8 shadow-card" />
            {results.length > 0 && <ul className="absolute left-0 right-0 top-full mt-1 overflow-hidden rounded-lg bg-panel p-1 shadow-pop">{results.map((r) => <li key={r.id}><button className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[13px] hover:bg-accent" onClick={() => { select(r.id); setQ(""); }}><span className="truncate">{r.label}</span><span className="ml-auto truncate font-mono text-[11px] text-muted-foreground">{r.hint}</span></button></li>)}</ul>}
          </div>
          <Dropdown>
            <DropdownTrigger asChild><Button size="sm" variant="outline" className="pointer-events-auto bg-panel shadow-card"><Boxes />Folders</Button></DropdownTrigger>
            <DropdownContent align="start" className="max-h-80 w-64 overflow-y-auto">
              <DropdownLabel>Jump to a folder</DropdownLabel>
              {layout.clusters.map((c) => <DropdownItem key={c.id} onSelect={() => enter(c.id)}><span className="block truncate font-medium">{c.label}</span><span className="block text-[11px] text-muted-foreground">{c.files.length} files{c.entries ? ` · ${c.entries} entry` : ""}{c.tests ? ` · ${c.tests} tests` : ""}</span></DropdownItem>)}
            </DropdownContent>
          </Dropdown>
          <Dropdown>
            <DropdownTrigger asChild><Button size="sm" variant="outline" className="pointer-events-auto bg-panel shadow-card"><Filter />Filters</Button></DropdownTrigger>
            <DropdownContent align="start" className="w-72 p-3">
              <div className="space-y-3 text-xs" onKeyDown={(e) => e.stopPropagation()}>
                <div><div className="mb-1.5 font-medium text-muted-foreground">Show nodes</div>
                  {([["folders", "Folders"], ["files", "Source files"], ["tests", "Test files"], ["symbols", "Functions & classes"]] as const).map(([k, l]) => <label key={k} className="flex items-center justify-between py-1"><span>{l}</span><Switch checked={types[k]} onCheckedChange={(v) => setTypes((t) => ({ ...t, [k]: v }))} label={l} /></label>)}
                  <label className="flex items-center justify-between py-1"><span>All functions at once (up to 80 files)</span><Switch checked={allSymbols} onCheckedChange={setAllSymbols} label="Show all functions" /></label></div>
                <div><div className="mb-1.5 font-medium text-muted-foreground">Show relationships</div>
                  {([["import", "Imports"], ["call", "Calls"], ["inherit", "Inheritance"], ["test", "Test coverage"]] as const).map(([k, l]) => <label key={k} className="flex items-center justify-between py-1"><span>{l}</span><Switch checked={rels[k]} onCheckedChange={(v) => setRels((r) => ({ ...r, [k]: v }))} label={l} /></label>)}
                  <label className="flex items-center justify-between py-1"><span>Only verified relationships</span><Switch checked={verifiedOnly} onCheckedChange={setVerifiedOnly} label="Only verified" /></label></div>
                <div><div className="mb-1.5 font-medium text-muted-foreground">Colour by</div><Segmented size="sm" value={colorBy} onChange={setColorBy} options={[{ value: "folder", label: "Folder" }, { value: "language", label: "Language" }, { value: "kind", label: "Type" }]} /></div>
                <label className="flex items-center justify-between py-1"><span>Reduce motion{osReduced ? " (set by your system)" : ""}</span><Switch checked={reduced} disabled={osReduced} onCheckedChange={setReduceMotion} label="Reduce motion" /></label>
              </div>
            </DropdownContent>
          </Dropdown>
          <Segmented size="sm" value={mode} onChange={(m) => setMode(m)} className="pointer-events-auto bg-panel shadow-card" options={[{ value: "3d", label: "3D", title: webgl === false ? "WebGL is not available in this browser" : "Interactive 3D view" }, { value: "2d", label: "2D", title: "Flat layout of the same data" }]} />
          <Button size="sm" variant="outline" className="pointer-events-auto bg-panel shadow-card" onClick={reset}><RotateCcw />Reset</Button>
          <Button size="sm" variant="ghost" className="pointer-events-auto" onClick={() => setLegend((l) => !l)}><CircleHelp />{legend ? "Hide legend" : "Legend"}</Button>
          {mode === "3d" && webgl === false && <Badge variant="warning" className="pointer-events-auto">WebGL unavailable: showing 2D</Badge>}
        </div>

        {focusCluster && (
          <div className="absolute left-3 top-14 z-10 mt-1 flex items-center gap-1.5 rounded-lg bg-panel px-2 py-1 text-xs shadow-card">
            <button onClick={exit} className="inline-flex items-center gap-1 text-primary hover:underline"><ChevronLeft className="size-3.5" />All folders</button><span className="text-muted-foreground">/</span><span className="font-medium">{focusCluster}</span>
            <button aria-label="Exit folder" onClick={exit} className="ml-1 text-muted-foreground hover:text-foreground"><X className="size-3.5" /></button>
          </div>
        )}
        {hoverTip && <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 -translate-x-1/2 rounded-lg bg-panel px-3 py-1.5 text-xs shadow-pop"><span className="font-medium">{hoverTip.label}</span>{hoverTip.kind === "file" && <span className="ml-2 font-mono text-muted-foreground">{hoverTip.id}</span>}</div>}
        {legend && <div className="pointer-events-none absolute bottom-3 left-3 z-10"><Legend colorBy={colorBy} /></div>}
        <div className="pointer-events-none absolute bottom-3 right-3 z-10 rounded-md bg-panel/90 px-2.5 py-1 text-[11px] text-muted-foreground shadow-card">{stat.files} files · {stat.symbols} symbols{graph.truncated.symbols ? ` (+${graph.truncated.symbols} not shown)` : ""} · {stat.verified_edges} verified / {stat.inferred_edges} inferred relationships{graph.truncated.files ? ` · ${graph.truncated.files} files omitted` : ""}</div>
        {onboard && <Onboarding onClose={closeOnboard} />}
      </div>
      {sel && (
        <div className="hidden w-[360px] shrink-0 border-l bg-panel md:block">
          <InfoPanel repoId={repoId} graph={graph} layout={layout} adj={adj} sel={sel} focusCluster={focusCluster} trace={trace} setTrace={setTrace} runTrace={runTrace} onSelect={(id) => select(id)} onEnter={enter} onExit={exit} onClose={() => setSel(null)} g={maps} targets={targets} />
        </div>
      )}
      {sel && (
        <div className="fixed inset-x-0 bottom-0 z-30 max-h-[60vh] overflow-hidden rounded-t-2xl border-t bg-panel shadow-pop md:hidden">
          <InfoPanel repoId={repoId} graph={graph} layout={layout} adj={adj} sel={sel} focusCluster={focusCluster} trace={trace} setTrace={setTrace} runTrace={runTrace} onSelect={(id) => select(id)} onEnter={enter} onExit={exit} onClose={() => setSel(null)} g={maps} targets={targets} />
        </div>
      )}
      <span className="sr-only" aria-live="polite">{sel ? `Selected ${maps.label(sel.id)}` : "Nothing selected"}</span>
    </div>
  );
}
