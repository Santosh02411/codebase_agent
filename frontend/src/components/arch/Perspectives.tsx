"use client";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactFlow, { Background, BackgroundVariant, Controls, MiniMap, ReactFlowProvider, useReactFlow } from "reactflow";
import "reactflow/dist/style.css";
import { Boxes, ExternalLink, FlaskConical, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { useStats } from "@/hooks/queries";
import { useTheme } from "@/lib/theme";
import { useOpenFile } from "@/hooks/useOpen";
import { basename, cn } from "@/lib/utils";
import type { Graph, GraphNode } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";
import { FileLink } from "@/components/common/bits";
import { clusterKeys } from "@/components/arch3d/layout3d";
import { buildFlow, edgeTypes, nodeTypes, type ArchData } from "./flow";

function useSystem(repoId: string) { return useQuery({ queryKey: ["system-graph", repoId], queryFn: () => api.graphSystem(repoId) }); }

function Flow({ graph, layout, onNode, selected }: { graph: Graph; layout: "force" | "layered" | "dag"; onNode: (n: GraphNode) => void; selected: string | null }) {
  const theme = useTheme((s) => s.theme);
  const rf = useReactFlow();
  const flow = useMemo(() => buildFlow({ graph, layout, selected, query: "", hiddenGroups: new Set(), hiddenKinds: new Set(), theme, colorBy: "folder", testFiles: new Set(graph.nodes.filter((n) => n.language === "test").map((n) => n.file)) }), [graph, layout, selected, theme]);
  useEffect(() => { const t = setTimeout(() => rf.fitView({ padding: 0.2, duration: 300 }), 80); return () => clearTimeout(t); }, [graph, rf]);
  return (
    <ReactFlow nodes={flow.nodes} edges={flow.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} minZoom={0.08} maxZoom={2.2} nodesConnectable={false} proOptions={{ hideAttribution: true }} onNodeClick={(_, n) => onNode((n.data as ArchData).raw)}>
      <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color={theme === "dark" ? "#2a2d36" : "#d4d8e0"} /><Controls showInteractive={false} /><MiniMap pannable zoomable nodeColor={() => "#818cf8"} maskColor={theme === "dark" ? "rgba(0,0,0,.55)" : "rgba(255,255,255,.6)"} />
    </ReactFlow>
  );
}

/** Folder-level dependencies: every folder cluster, linked by the imports that cross between them. */
export function FolderGraph({ repoId }: { repoId: string }) {
  const q = useSystem(repoId);
  const openFile = useOpenFile();
  const [sel, setSel] = useState<string | null>(null);
  const data = useMemo(() => {
    const g = q.data; if (!g) return null;
    const ck = clusterKeys(g.files); const counts = new Map<string, number>();
    ck.forEach((c) => counts.set(c, (counts.get(c) ?? 0) + 1));
    const w = new Map<string, { n: number; verified: number }>();
    for (const e of g.edges) {
      if (e.type === "call" || e.type === "inherit") continue;
      const a = ck.get(e.source), b = ck.get(e.target); if (!a || !b || a === b) continue;
      const k = `${a}\u0000${b}`; const cur = w.get(k) ?? { n: 0, verified: 0 }; cur.n += 1; cur.verified += e.verified ? 1 : 0; w.set(k, cur);
    }
    const nodes: GraphNode[] = [...counts].map(([id, n]) => ({ id, name: id, file: id, kind: "directory", count: n } as GraphNode));
    const edges = [...w].map(([k, v]) => { const [source, target] = k.split("\u0000"); return { source, target, weight: v.n, confidence: v.verified === v.n ? "import" : "ambiguous" }; });
    return { graph: { collapsed: true, nodes, edges } as unknown as Graph, files: ck, counts };
  }, [q.data]);
  if (q.isLoading) return <div className="p-10"><Skeleton className="h-96" /></div>;
  if (q.isError) return <div className="p-10"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  if (!data || !data.graph.nodes.length) return <EmptyState className="h-full" title="No folders to show" />;
  const files = sel ? [...data.files].filter(([, c]) => c === sel).map(([f]) => f) : [];
  return (
    <div className="flex h-full min-h-0">
      <div className="relative min-w-0 flex-1"><ReactFlowProvider><Flow graph={data.graph} layout="dag" selected={sel} onNode={(n) => setSel((c) => (c === n.id ? null : n.id))} /></ReactFlowProvider>
        <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-panel/90 px-2.5 py-1 text-[11px] text-muted-foreground shadow-card">Folders linked by the imports and test links between them · click a folder to list its files</div></div>
      {sel && <aside className="hidden w-72 shrink-0 overflow-y-auto border-l bg-panel p-4 md:block"><div className="mb-1 flex items-center gap-2 text-[13px] font-semibold"><Boxes className="size-4 text-primary" />{sel}<Badge variant="outline">{files.length} files</Badge></div>
        <ul className="mt-2">{files.slice(0, 60).map((f) => <li key={f}><button className="w-full truncate rounded px-1.5 py-1 text-left font-mono text-[12px] hover:bg-accent/60" onClick={() => openFile(f)}>{basename(f)}</button></li>)}</ul></aside>}
    </div>
  );
}

/** Which tests exercise which modules: verified (the test imports it) vs inferred (the names match). */
export function TestMap({ repoId }: { repoId: string }) {
  const q = useSystem(repoId);
  const ins = useQuery({ queryKey: ["insights", repoId], queryFn: () => api.insights(repoId) });
  const openFile = useOpenFile();
  const data = useMemo(() => {
    const g = q.data; if (!g) return null;
    const te = g.edges.filter((e) => e.type === "test");
    const ids = new Set(te.flatMap((e) => [e.source, e.target]));
    const nodes: GraphNode[] = g.files.filter((f) => ids.has(f.id)).map((f) => ({ id: f.id, name: basename(f.id), file: f.id, kind: "file", level: f.is_test ? -1 : 0, language: f.is_test ? "test" : f.language, symbols: f.symbols } as GraphNode));
    const edges = te.map((e) => ({ source: e.source, target: e.target, weight: e.weight, confidence: e.verified ? "import" : "ambiguous" }));
    return { graph: { collapsed: false, nodes, edges } as unknown as Graph, verified: te.filter((e) => e.verified).length, inferred: te.filter((e) => !e.verified).length };
  }, [q.data]);
  if (q.isLoading) return <div className="p-10"><Skeleton className="h-96" /></div>;
  if (q.isError) return <div className="p-10"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  const untested = ins.data?.risks.untested_modules ?? [];
  return (
    <div className="flex h-full min-h-0">
      <div className="relative min-w-0 flex-1">
        {!data || data.graph.nodes.length === 0 ? <EmptyState className="h-full" icon={<FlaskConical className="size-5" />} title="No test-to-source links found" description="Either the project has no tests, or the tests don’t import the modules they exercise in a way the parser can follow." /> : <ReactFlowProvider><Flow graph={data.graph} layout="layered" selected={null} onNode={(n) => openFile(n.file)} /></ReactFlowProvider>}
        {data && <div className="pointer-events-none absolute left-3 top-3 flex gap-2"><Badge variant="success">{data.verified} verified (test imports module)</Badge><Badge variant="warning">{data.inferred} inferred (names match, dashed)</Badge></div>}
      </div>
      <aside className="hidden w-72 shrink-0 overflow-y-auto border-l bg-panel p-4 md:block">
        <div className="mb-1 flex items-center gap-2 text-[13px] font-semibold"><TriangleAlert className="size-4 text-warning" />Not reached by any test</div>
        <p className="mb-2 text-xs text-muted-foreground">No test imports these modules (directly or through other modules) and none is named after them.</p>
        {untested.length === 0 ? <p className="text-xs text-success">Every module with code is reached by at least one test.</p> : <ul>{untested.map((f) => <li key={f}><FileLink path={f} /></li>)}</ul>}
      </aside>
    </div>
  );
}

/** Data models found by the parser. Relationships between models are not extracted by the backend, so none are drawn. */
export function ModelsView({ repoId }: { repoId: string }) {
  const stats = useStats(repoId);
  const openFile = useOpenFile();
  if (stats.isLoading) return <div className="p-10"><Skeleton className="h-64" /></div>;
  const models = stats.data?.models ?? [];
  if (!models.length) return <EmptyState className="h-full" icon={<Boxes className="size-5" />} title="No data models detected" description="The parser looks for ORM models and schema classes (SQLAlchemy, Django, Pydantic, dataclasses, JPA, GORM...). None were found in this project." />;
  return (
    <div className="h-full overflow-y-auto p-5">
      <div className="mx-auto max-w-5xl">
        <p className="mb-3 text-xs text-muted-foreground">{models.length} model{models.length === 1 ? "" : "s"} found. Field-level details and relationships between models are not extracted by the parser, so none are shown.</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{models.map((m) => (
          <button key={m.name + m.file} onClick={() => openFile(m.file, m.line)} className="group rounded-xl bg-panel p-3.5 text-left shadow-card transition-all hover:-translate-y-0.5 hover:shadow-pop">
            <div className="flex items-center gap-2"><Boxes className="size-4 text-primary" /><span className="text-[13px] font-semibold">{m.name}</span><ExternalLink className="ml-auto size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" /></div>
            <div className="mt-1.5 flex flex-wrap gap-1.5"><Badge variant="secondary">{m.framework}</Badge><Badge variant="outline">{m.fields} fields</Badge></div>
            <div className="mt-2 truncate font-mono text-[11px] text-muted-foreground">{m.file}:{m.line}</div>
          </button>))}</div>
      </div>
    </div>
  );
}
