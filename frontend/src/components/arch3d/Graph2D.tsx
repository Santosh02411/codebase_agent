"use client";
import { useMemo } from "react";
import ReactFlow, { Background, BackgroundVariant, Controls, MarkerType, MiniMap, ReactFlowProvider, type Edge, type Node } from "reactflow";
import "reactflow/dist/style.css";
import { nodeTypes, edgeTypes, type ArchData } from "@/components/arch/flow";
import { useTheme } from "@/lib/theme";
import type { SEdge, SNode } from "./Scene3D";

export type E2 = SEdge & { s: string; t: string };

/** The same data and the same selection as the 3D view, laid out flat. Used for reduced-motion users, devices without WebGL, and anyone who prefers 2D. */
function Flat({ nodes, edges, onPick, onEmpty }: { nodes: SNode[]; edges: E2[]; onPick: (n: SNode) => void; onEmpty: () => void }) {
  const theme = useTheme((s) => s.theme);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const rf = useMemo(() => {
    const ns = nodes.filter((n) => n.kind !== "cluster" || true).map<Node<ArchData>>((n) => ({
      id: n.id, type: "arch", position: { x: n.x * 46, y: n.z * 46 + n.y * 14 },
      style: { width: n.kind === "cluster" ? 150 : 124, height: 30 },
      data: { label: n.label, sub: n.sub ?? "", kind: n.kind === "cluster" ? "directory" : n.kind === "symbol" ? "function" : "file", color: n.color, state: n.emphasis === 2 ? "selected" : n.emphasis === 1 ? "neighbor" : "normal", match: false, focus: false, test: n.shape === "box" && n.kind === "file",
              raw: { id: n.id, name: n.label, file: n.id, kind: n.kind } as never },
    }));
    const es = edges.filter((e) => byId.has(e.s) && byId.has(e.t)).map<Edge>((e, i) => {
      const col = e.hi === "out" ? "#38bdf8" : e.hi === "in" ? "#fbbf24" : e.hi === "path" ? "#4ade80" : theme === "dark" ? "#6b7280" : "#8a93a3";
      return { id: `${e.key}:${i}`, source: e.s, target: e.t, type: "float", data: { guessed: e.dashed }, markerEnd: { type: MarkerType.ArrowClosed, color: col, width: 12, height: 12 }, style: { stroke: col, strokeWidth: e.hi ? 2 : 1, opacity: e.hi ? 1 : 0.55 } };
    });
    return { ns, es };
  }, [nodes, edges, byId, theme]);
  return (
    <ReactFlow nodes={rf.ns} edges={rf.es} nodeTypes={nodeTypes} edgeTypes={edgeTypes} fitView minZoom={0.05} maxZoom={2.5} nodesConnectable={false} proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => { const x = byId.get(n.id); if (x) onPick(x); }} onPaneClick={onEmpty}>
      <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color={theme === "dark" ? "#2a2d36" : "#d4d8e0"} />
      <Controls showInteractive={false} /><MiniMap pannable zoomable nodeColor={() => "#818cf8"} maskColor={theme === "dark" ? "rgba(0,0,0,.55)" : "rgba(255,255,255,.6)"} />
    </ReactFlow>
  );
}
export default function Graph2D(p: { nodes: SNode[]; edges: E2[]; onPick: (n: SNode) => void; onEmpty: () => void }) { return <ReactFlowProvider><Flat {...p} /></ReactFlowProvider>; }
