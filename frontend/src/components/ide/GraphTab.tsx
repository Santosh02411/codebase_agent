"use client";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, ExternalLink, Maximize2, Network } from "lucide-react";
import { useCallGraph, useImpact, useModuleGraph, useSymbolDetail } from "@/hooks/queries";
import { useIde, type GraphFocus } from "@/store/ide";
import type { Graph, SymbolRef } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { clip, force, label, layered, type Pos } from "@/lib/graphLayout";

const KIND_COLOR: Record<string, string> = { function: "#a78bfa", method: "#818cf8", class: "#fbbf24", interface: "#2dd4bf", struct: "#fb923c", trait: "#2dd4bf", enum: "#f472b6", type: "#94a3b8" };
const LANG_COLOR: Record<string, string> = { python: "#3572A5", javascript: "#c9b628", typescript: "#3178c6", java: "#b07219", go: "#00ADD8", rust: "#dea584", c: "#8f8f8f", cpp: "#f34b7d" };


function SymbolList({ title, items, onPick }: { title: string; items: SymbolRef[]; onPick: (s: SymbolRef) => void }) {
  if (!items.length) return null;
  return (
    <div className="pt-2">
      <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title} · {items.length}</div>
      {items.map((s) => (
        <button key={s.id} onClick={() => onPick(s)} className="flex w-full items-center gap-1.5 px-3 py-1 text-left hover:bg-accent/50" title={`${s.file}:${s.start}`}>
          <span className="size-2 shrink-0 rounded-full" style={{ background: KIND_COLOR[s.kind] ?? "#888" }} />
          <span className="truncate">{s.qualname}</span>
          {s.confidence && s.confidence !== "import" && s.confidence !== "local" && s.confidence !== "self" && <Badge variant={s.confidence === "ambiguous" ? "warning" : "outline"} className="ml-auto">{s.confidence}</Badge>}
        </button>
      ))}
    </div>
  );
}

export function GraphTab({ repoId, graph }: { repoId: string; graph: GraphFocus }) {
  const { openFile, openGraph } = useIde.getState();
  const calls = graph.mode === "calls";
  const [depth, setDepth] = useState(calls ? 2 : 1);
  const [direction, setDirection] = useState("both");
  const [selected, setSelected] = useState<string | null>(null);
  const callQ = useCallGraph(repoId, calls ? graph.focus : undefined, depth, direction);
  const modQ = useModuleGraph(repoId, graph.focus, depth, direction, !calls);
  const data: Graph | undefined = calls ? callQ.data : modQ.data;
  const error = (calls ? callQ.error : modQ.error) as Error | null;
  const focusId = graph.focus;
  const sel = selected ?? focusId ?? null;

  const pos = useMemo(() => {
    if (!data?.nodes.length) return new Map<string, Pos>();
    return focusId || calls ? layered(data.nodes) : force(data.nodes, data.edges);
  }, [data, focusId, calls]);
  const byId = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);

  // pan & zoom
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const fit = useCallback(() => {
    const el = box.current;
    if (!el || !pos.size) return;
    const ps = [...pos.values()];
    const minX = Math.min(...ps.map((p) => p.x)), maxX = Math.max(...ps.map((p) => p.x + p.w));
    const minY = Math.min(...ps.map((p) => p.y)), maxY = Math.max(...ps.map((p) => p.y + p.h));
    const k = Math.min(1.4, (el.clientWidth - 60) / (maxX - minX || 1), (el.clientHeight - 60) / (maxY - minY || 1));
    setView({ k, x: el.clientWidth / 2 - ((minX + maxX) / 2) * k, y: el.clientHeight / 2 - ((minY + maxY) / 2) * k });
  }, [pos]);
  useLayoutEffect(fit, [fit]);
  useEffect(() => { setSelected(null); }, [graph.focus, graph.mode]);

  const sym = useSymbolDetail(repoId, calls ? sel ?? undefined : undefined);
  const impactPath = !calls ? (sel && !byId.get(sel)?.kind?.includes("directory") ? sel : undefined) : undefined;
  const impact = useImpact(repoId, impactPath && sel && byId.get(sel)?.file === sel ? impactPath : undefined);
  const selNode = sel ? byId.get(sel) : undefined;

  const onPick = (s: SymbolRef) => (byId.has(s.id) ? setSelected(s.id) : openGraph("calls", s.id, `Calls: ${s.qualname}`));

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5">
        <Network className="size-4 text-primary" />
        <span className="font-medium">{calls ? "Call graph" : focusId ? "Module graph" : "Repository module graph"}</span>
        {focusId && <span className="truncate font-mono text-[11px] text-muted-foreground">{focusId.split("::").pop()}</span>}
        {focusId && (
          <>
            <label className="ml-2 flex items-center gap-1 text-[11px] text-muted-foreground">Depth
              <select value={depth} onChange={(e) => setDepth(Number(e.target.value))} className="h-6 rounded border border-input bg-background px-1">{[1, 2, 3, 4].map((d) => <option key={d}>{d}</option>)}</select></label>
            <label className="flex items-center gap-1 text-[11px] text-muted-foreground">Show
              <select value={direction} onChange={(e) => setDirection(e.target.value)} className="h-6 rounded border border-input bg-background px-1">
                <option value="both">both directions</option>
                {calls ? <><option value="callers">callers only</option><option value="callees">callees only</option></> : <><option value="imports">imports only</option><option value="imported_by">imported by only</option></>}
              </select></label>
          </>
        )}
        <Button size="xs" variant="ghost" className="ml-auto" onClick={fit}><Maximize2 /> Fit</Button>
        <div className="flex items-center gap-3 text-[10.5px] text-muted-foreground">
          <span className="flex items-center gap-1"><span className="h-px w-5 bg-slate-400" />resolved</span>
          <span className="flex items-center gap-1"><span className="h-px w-5 border-t border-dashed border-slate-400" />guessed by name</span>
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        <div ref={box} className="relative min-w-0 flex-1 cursor-grab overflow-hidden bg-background active:cursor-grabbing"
          onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY }; (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); }}
          onPointerMove={(e) => { if (!drag.current) return; const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y; drag.current = { x: e.clientX, y: e.clientY }; setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy })); }}
          onPointerUp={() => { drag.current = null; }}
          onWheel={(e) => { const r = box.current!.getBoundingClientRect(); const mx = e.clientX - r.left, my = e.clientY - r.top; const f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
            setView((v) => { const k = Math.min(3, Math.max(0.15, v.k * f)); return { k, x: mx - ((mx - v.x) / v.k) * k, y: my - ((my - v.y) / v.k) * k }; }); }}>
          {!data && !error && <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">Building graph…</div>}
          {error && <div className="p-4 text-destructive">{error.message}</div>}
          {data && data.nodes.length <= 1 && data.edges.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-muted-foreground">{calls ? "This function has no resolved callers or callees. Calls to external libraries and dynamic calls aren’t shown." : "No internal imports found for this file."}</div>
          )}
          {data && (
            <svg className="size-full select-none">
              <defs>
                <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#94a3b8" /></marker>
                <marker id="arrow-hi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#60a5fa" /></marker>
              </defs>
              <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
                {data.edges.map((e, i) => {
                  const a = pos.get(e.source), b = pos.get(e.target);
                  if (!a || !b) return null;
                  const hi = sel === e.source || sel === e.target;
                  const [ex, ey] = clip(a, b);
                  const layeredLayout = focusId || calls;
                  const sx = layeredLayout ? (b.x >= a.x + a.w ? a.x + a.w : a.x + a.w / 2) : a.x + a.w / 2;
                  const sy = a.y + a.h / 2;
                  const d = layeredLayout && b.x >= a.x + a.w ? `M${sx} ${sy} C${sx + 50} ${sy} ${b.x - 50} ${b.y + b.h / 2} ${b.x} ${b.y + b.h / 2}` : `M${sx} ${sy} L${ex} ${ey}`;
                  return <path key={i} d={d} fill="none" stroke={hi ? "#60a5fa" : "#64748b"} strokeWidth={hi ? 1.8 : 1 + Math.min(3, (e.weight ?? 1) / 4)} strokeOpacity={hi ? 1 : 0.55}
                    strokeDasharray={e.confidence === "unique" || e.confidence === "ambiguous" ? "4 3" : undefined} markerEnd={hi ? "url(#arrow-hi)" : "url(#arrow)"} />;
                })}
                {data.nodes.map((n) => {
                  const p = pos.get(n.id);
                  if (!p) return null;
                  const color = calls ? KIND_COLOR[n.kind ?? ""] ?? "#888" : n.kind === "directory" ? "#64748b" : LANG_COLOR[n.language ?? ""] ?? "#64748b";
                  const isSel = n.id === sel, isFocus = n.id === focusId;
                  const text = label(n);
                  return (
                    <g key={n.id} transform={`translate(${p.x} ${p.y})`} className="cursor-pointer" onClick={(e) => { e.stopPropagation(); setSelected(n.id); }}
                      onDoubleClick={() => (n.kind === "directory" ? undefined : openFile(n.file, n.start))}>
                      <rect width={p.w} height={p.h} rx={7} fill="#1e2330" stroke={isSel ? "#60a5fa" : isFocus ? "#fbbf24" : color} strokeWidth={isSel || isFocus ? 2.2 : 1.2} />
                      <rect width={4} height={p.h} rx={2} fill={color} />
                      <text x={12} y={p.h / 2 + 4} fontSize={11.5} fill="#e2e8f0" fontFamily="ui-monospace, Menlo, monospace">{text.length > 32 ? `${text.slice(0, 31)}…` : text}</text>
                      {n.count && n.count > 1 && <text x={p.w - 8} y={p.h / 2 + 4} fontSize={10} textAnchor="end" fill="#94a3b8">{n.count}</text>}
                      <title>{`${n.file}${n.start ? `:${n.start}` : ""}\n${n.signature ?? ""}\n(double-click to open)`}</title>
                    </g>
                  );
                })}
              </g>
            </svg>
          )}
          <div className="pointer-events-none absolute bottom-2 left-3 text-[10.5px] text-muted-foreground">
            {data ? `${data.nodes.length} nodes · ${data.edges.length} edges` : ""}{data?.collapsed ? " · grouped by folder (large repository)" : ""} · drag to pan, scroll to zoom, double-click a node to open it
          </div>
        </div>

        <ScrollArea className="w-72 shrink-0 border-l bg-panel">
          {calls && sym.data && (
            <div className="pb-3">
              <div className="space-y-1.5 border-b p-3">
                <div className="flex items-center gap-1.5"><Badge variant="secondary">{sym.data.kind}</Badge><span className="truncate font-semibold">{sym.data.qualname}</span></div>
                <button onClick={() => openFile(sym.data!.file, sym.data!.start, sym.data!.end)} className="flex items-center gap-1 font-mono text-[11px] text-primary hover:underline"><ExternalLink className="size-3" />{sym.data.file}:{sym.data.start}</button>
                {sym.data.signature && <pre className="overflow-x-auto rounded bg-background p-1.5 font-mono text-[10.5px]">{sym.data.signature}</pre>}
                {sym.data.doc && <div className="text-[12px] text-muted-foreground">{sym.data.doc}</div>}
                {sym.data.route && <Badge variant="success">{sym.data.route}</Badge>}
                {sym.data.tags.filter((t) => t !== "api").map((t) => <Badge key={t} variant="outline" className="mr-1">{t}</Badge>)}
              </div>
              <SymbolList title="Called by" items={sym.data.callers} onPick={onPick} />
              <SymbolList title="Calls" items={sym.data.callees} onPick={onPick} />
              <SymbolList title="Extends" items={sym.data.base_symbols} onPick={onPick} />
              <SymbolList title="Subclassed by" items={sym.data.derived} onPick={onPick} />
              {sym.data.bases.length > sym.data.base_symbols.length && <div className="px-3 pt-2 text-[11px] text-muted-foreground">External bases: {sym.data.bases.filter((b) => !sym.data!.base_symbols.some((s) => s.qualname.endsWith(b.split(".").pop()!))).join(", ")}</div>}
              {sym.data.unresolved_calls.length > 0 && (
                <div className="px-3 pt-3"><div className="pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Not resolved (library or dynamic)</div>
                  <div className="flex flex-wrap gap-1">{sym.data.unresolved_calls.slice(0, 14).map((c) => <Badge key={c} variant="outline">{c}</Badge>)}</div></div>
              )}
              <div className="px-3 pt-3"><Button size="xs" variant="outline" onClick={() => openGraph("modules", sym.data!.file, `Modules: ${sym.data!.file.split("/").pop()}`)}><Network /> Module graph of this file</Button></div>
            </div>
          )}
          {!calls && selNode && (
            <div className="pb-3">
              <div className="space-y-1.5 border-b p-3">
                <div className="truncate font-semibold">{selNode.name}</div>
                <div className="break-all font-mono text-[11px] text-muted-foreground">{selNode.file}</div>
                {selNode.kind !== "directory" && <div className="flex gap-1.5"><Button size="xs" variant="secondary" onClick={() => openFile(selNode.file)}><ExternalLink /> Open</Button><Button size="xs" variant="outline" onClick={() => openGraph("modules", selNode.file, `Modules: ${selNode.name}`)}><Network /> Focus</Button></div>}
                {selNode.symbols !== undefined && <div className="text-[11px] text-muted-foreground">{selNode.symbols} symbols · {selNode.language}</div>}
                {selNode.external && selNode.external.length > 0 && <div className="flex flex-wrap gap-1 pt-1">{selNode.external.map((x) => <Badge key={x} variant="outline">{x}</Badge>)}</div>}
              </div>
              {impact.data && (
                <div className="pt-2">
                  <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">If you change this file · {impact.data.dependents.length} files affected</div>
                  {impact.data.dependents.slice(0, 30).map((d) => (
                    <button key={d.file} onClick={() => openFile(d.file)} className="flex w-full items-center gap-1.5 px-3 py-1 text-left hover:bg-accent/50"><ArrowRight className="size-3 text-muted-foreground" /><span className="truncate font-mono text-[11px]">{d.file}</span><Badge variant="secondary" className="ml-auto">{d.distance === 1 ? "direct" : `via ${d.distance}`}</Badge></button>
                  ))}
                  {impact.data.tests.length > 0 && <div className="px-3 pt-2"><div className="pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Tests to run</div>{impact.data.tests.map((t) => <button key={t} onClick={() => openFile(t)} className="block w-full truncate py-0.5 text-left font-mono text-[11px] text-success hover:underline">{t}</button>)}</div>}
                </div>
              )}
            </div>
          )}
          {!selNode && !sym.data && <div className={cn("p-3 text-muted-foreground")}>Click a node to see details.</div>}
        </ScrollArea>
      </div>
    </div>
  );
}
