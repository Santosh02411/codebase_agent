"use client";
import { memo } from "react";
import { BaseEdge, Handle, MarkerType, Position, getStraightPath, useStore, type Edge, type EdgeProps, type Node, type NodeProps } from "reactflow";
import { Box, FileCode2, FolderTree, FunctionSquare, FlaskConical } from "lucide-react";
import { clip, force, label, layered, widthOf, H, type Pos } from "@/lib/graphLayout";
import { dagLayout } from "@/lib/dagLayout";
import { cn } from "@/lib/utils";
import type { Graph, GraphNode } from "@/lib/types";

export const FOLDER_COLORS = ["hsl(var(--chart-1))", "hsl(var(--chart-2))", "hsl(var(--chart-3))", "hsl(var(--chart-4))", "hsl(var(--chart-5))", "hsl(var(--chart-6))"];
export const groupOf = (file: string) => file.split("/").slice(0, -1).slice(0, 2).join("/") || ".";
export const topDir = (file: string) => (file.includes("/") ? file.split("/")[0] : "(root)");
const hash = (s: string) => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
export const colorOf = (key: string) => FOLDER_COLORS[hash(key) % FOLDER_COLORS.length];

export interface ArchData { label: string; sub: string; kind: string; color: string; state: "normal" | "selected" | "neighbor" | "dim"; match: boolean; focus: boolean; test: boolean; raw: GraphNode }

const KIND_ICON = (k?: string) => (k === "directory" ? <FolderTree className="size-3.5" /> : k === "class" || k === "struct" || k === "interface" || k === "enum" ? <Box className="size-3.5" /> : k && k !== "file" ? <FunctionSquare className="size-3.5" /> : <FileCode2 className="size-3.5" />);

export const ArchNode = memo(function ArchNode({ data }: NodeProps<ArchData>) {
  return (
    <div title={data.raw.file ? `${data.raw.file}${data.raw.start ? `:${data.raw.start}` : ""}` : data.label}
      className={cn("flex h-full items-center gap-1.5 rounded-md border bg-panel px-2 text-[12px] shadow-card transition-all", data.state === "dim" && "opacity-25", data.state === "selected" && "ring-2 ring-primary", data.state === "neighbor" && "ring-1 ring-primary/50",
        data.match && "ring-2 ring-warning", data.focus && "bg-primary/10", data.test && "border-success/60")}
      style={{ borderLeft: `3px solid ${data.color}` }}>
      <Handle type="target" position={Position.Left} className="!size-0 !min-h-0 !min-w-0 !border-0 !bg-transparent" />
      <span style={{ color: data.color }}>{data.test ? <FlaskConical className="size-3.5" /> : KIND_ICON(data.kind)}</span>
      <span className="min-w-0 flex-1 truncate font-medium">{data.label}</span>
      {data.sub && <span className="shrink-0 text-[10.5px] tabular-nums text-muted-foreground">{data.sub}</span>}
      <Handle type="source" position={Position.Right} className="!size-0 !min-h-0 !min-w-0 !border-0 !bg-transparent" />
    </div>
  );
});

/** Straight edge between node borders (not fixed handles), so force-laid-out graphs stay readable. */
export const FloatingEdge = memo(function FloatingEdge({ id, source, target, style, markerEnd, data }: EdgeProps<{ weight?: number; guessed?: boolean; vertical?: boolean }>) {
  const s = useStore((st) => st.nodeInternals.get(source));
  const t = useStore((st) => st.nodeInternals.get(target));
  if (!s || !t || !s.width || !t.width || !s.height || !t.height || !s.positionAbsolute || !t.positionAbsolute) return null;
  if (data?.vertical) {                      // top-to-bottom graphs: leave the bottom of the importer, enter the top of the imported file, in a smooth curve
    const below = t.positionAbsolute.y >= s.positionAbsolute.y;
    const sx = s.positionAbsolute.x + s.width / 2, sy = s.positionAbsolute.y + (below ? s.height : 0);
    const tx = t.positionAbsolute.x + t.width / 2, ty = t.positionAbsolute.y + (below ? 0 : t.height);
    const my = (sy + ty) / 2;
    return <BaseEdge id={id} path={`M${sx},${sy} C${sx},${my} ${tx},${my} ${tx},${ty}`} markerEnd={markerEnd} style={{ ...style, strokeDasharray: data?.guessed ? "4 3" : undefined }} />;
  }
  const a: Pos = { x: s.positionAbsolute.x, y: s.positionAbsolute.y, w: s.width, h: s.height };
  const b: Pos = { x: t.positionAbsolute.x, y: t.positionAbsolute.y, w: t.width, h: t.height };
  const [tx, ty] = clip(a, b);
  const [sx, sy] = clip(b, a);
  const [path] = getStraightPath({ sourceX: sx, sourceY: sy, targetX: tx, targetY: ty });
  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={{ ...style, strokeDasharray: data?.guessed ? "4 3" : undefined }} />;
});

export const nodeTypes = { arch: ArchNode };
export const edgeTypes = { float: FloatingEdge };

export interface BuildOpts { graph: Graph; layout: "force" | "layered" | "dag"; focusId?: string; selected?: string | null; query: string; hiddenGroups: Set<string>; hiddenKinds: Set<string>; theme: "light" | "dark"; testFiles?: Set<string>; colorBy: "folder" | "kind" }

const KIND_COLORS: Record<string, string> = { function: "hsl(var(--chart-1))", method: "hsl(var(--chart-6))", class: "hsl(var(--chart-4))", interface: "hsl(var(--chart-2))", struct: "hsl(var(--chart-5))", enum: "hsl(var(--chart-5))", file: "hsl(var(--chart-1))", directory: "hsl(var(--chart-2))" };

/** Graph data from the backend -> React Flow nodes and edges, with search match, selection/neighbour highlighting and filters applied. */
export function buildFlow(o: BuildOpts): { nodes: Node<ArchData>[]; edges: Edge[]; hidden: number } {
  const visible = o.graph.nodes.filter((n) => !o.hiddenGroups.has(n.kind === "directory" ? n.name : topDir(n.file)) && !o.hiddenKinds.has(n.kind ?? "file"));
  const ids = new Set(visible.map((n) => n.id));
  const links = o.graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  const extra = (n: GraphNode) => (n.count && n.count > 1 ? 40 : 14);
  const pos: Map<string, Pos> = o.layout === "force" ? force(visible, links)
    : o.layout === "dag" ? new Map([...dagLayout(visible.map((n) => ({ id: n.id, w: widthOf(n) + extra(n), h: H, label: label(n) })), links.map((e) => ({ source: e.source, target: e.target })), { gapX: 48, gapY: 90, maxRow: 8 })].map(([k, v]) => [k, { x: v.x, y: v.y, w: v.w - extra(visible.find((n) => n.id === k)!), h: v.h }] as [string, Pos]))
    : layered(visible);
  const sel = o.selected ?? null;
  const nb = new Set<string>();
  if (sel) for (const e of links) { if (e.source === sel) nb.add(e.target); if (e.target === sel) nb.add(e.source); }
  const q = o.query.trim().toLowerCase();
  const nodes = visible.map<Node<ArchData>>((n) => {
    const p = pos.get(n.id) ?? { x: 0, y: 0, w: widthOf(n), h: H };
    const lab = label(n);
    const match = !!q && (lab.toLowerCase().includes(q) || n.file.toLowerCase().includes(q));
    const state = sel ? (n.id === sel ? "selected" : nb.has(n.id) ? "neighbor" : "dim") : q && !match ? "dim" : "normal";
    return {
      id: n.id, type: "arch", position: { x: p.x, y: p.y }, style: { width: p.w + (n.count && n.count > 1 ? 40 : 14), height: H }, draggable: true,
      data: { label: lab, sub: n.kind === "directory" ? `${n.count ?? 0} files` : n.count && n.count > 1 ? `${n.count}` : n.symbols ? `${n.symbols}` : "", kind: n.kind ?? "file", match, focus: n.id === o.focusId, state,
              color: o.colorBy === "kind" ? (KIND_COLORS[n.kind ?? "file"] ?? "hsl(var(--chart-1))") : colorOf(n.kind === "directory" ? n.name.split("/")[0] : topDir(n.file)), test: !!o.testFiles?.has(n.file), raw: n },
    };
  });
  const dark = o.theme === "dark";
  const base = dark ? "#6b7280" : "#8a93a3", hi = dark ? "#a5b4fc" : "#4f46e5", out = dark ? "#7dd3fc" : "#0369a1", inc = dark ? "#fcd34d" : "#b45309";
  const edges = links.map<Edge>((e, i) => {
    const touches = sel && (e.source === sel || e.target === sel);
    const col = touches ? (e.source === sel ? out : inc) : base;
    const dim = sel ? !touches : !!q;
    return { id: `${e.source}->${e.target}:${i}`, source: e.source, target: e.target, type: "float", data: { weight: e.weight, guessed: e.confidence === "ambiguous" || e.confidence === "name", vertical: o.layout === "dag" },
      markerEnd: { type: MarkerType.ArrowClosed, color: col, width: 14, height: 14 }, style: { stroke: o.theme ? col : hi, strokeWidth: touches ? 2 : Math.min(3, 1 + Math.log2((e.weight ?? 1) + 1) * 0.5), opacity: dim ? 0.1 : touches ? 1 : links.length > 60 ? 0.32 : 0.6 } };
  });
  return { nodes, edges, hidden: o.graph.nodes.length - visible.length };
}
