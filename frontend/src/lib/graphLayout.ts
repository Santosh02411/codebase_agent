import type { GraphEdge, GraphNode } from "./types";

export interface Pos { x: number; y: number; w: number; h: number }
export const H = 30;
export const label = (n: GraphNode) => (n.kind === "directory" ? n.name : n.qualname ?? n.name);
export const widthOf = (n: GraphNode) => Math.min(230, Math.max(90, label(n).length * 6.6 + 28));

/** Callers on the left, the focus in the middle, callees on the right. */
export function layered(nodes: GraphNode[]): Map<string, Pos> {
  const cols = new Map<number, GraphNode[]>();
  nodes.forEach((n) => cols.set(n.level ?? 0, [...(cols.get(n.level ?? 0) ?? []), n]));
  const levels = [...cols.keys()].sort((a, b) => a - b);
  const out = new Map<string, Pos>();
  let x = 0;
  for (const lv of levels) {
    const col = cols.get(lv)!.sort((a, b) => (a.file + label(a)).localeCompare(b.file + label(b)));
    const w = Math.max(...col.map(widthOf));
    col.forEach((n, i) => out.set(n.id, { x, y: (i - (col.length - 1) / 2) * (H + 16), w: widthOf(n), h: H }));
    x += w + 110;
  }
  return out;
}

/** Small deterministic force layout for the whole-repository module graph. */
export function force(nodes: GraphNode[], edges: GraphEdge[]): Map<string, Pos> {
  const n = nodes.length;
  const R = 90 + n * 9;
  const p = nodes.map((_, i) => ({ x: R * Math.cos((2 * Math.PI * i) / n), y: R * Math.sin((2 * Math.PI * i) / n), vx: 0, vy: 0 }));
  const idx = new Map(nodes.map((nd, i) => [nd.id, i]));
  const links = edges.map((e) => [idx.get(e.source), idx.get(e.target)] as const).filter((l): l is readonly [number, number] => l[0] !== undefined && l[1] !== undefined);
  const k = 120 + Math.sqrt(n) * 8;
  for (let it = 0; it < 320; it++) {
    const t = 1 - it / 320;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      let dx = p[i].x - p[j].x, dy = p[i].y - p[j].y;
      const d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2), f = (k * k) / d2;
      dx /= d; dy /= d;
      p[i].vx += dx * f; p[i].vy += dy * f; p[j].vx -= dx * f; p[j].vy -= dy * f;
    }
    for (const [a, b] of links) {
      const dx = p[b].x - p[a].x, dy = p[b].y - p[a].y, d = Math.sqrt(dx * dx + dy * dy) + 0.01, f = (d * d) / (k * 3);
      p[a].vx += (dx / d) * f; p[a].vy += (dy / d) * f; p[b].vx -= (dx / d) * f; p[b].vy -= (dy / d) * f;
    }
    for (const q of p) {
      q.vx -= q.x * 0.02; q.vy -= q.y * 0.02;
      const m = Math.hypot(q.vx, q.vy) || 1, cap = 40 * t + 2;
      q.x += (q.vx / m) * Math.min(m, cap); q.y += (q.vy / m) * Math.min(m, cap); q.vx = 0; q.vy = 0;
    }
  }
  const boxes = nodes.map((nd, i) => ({ x: p[i].x, y: p[i].y, w: widthOf(nd), h: H }));
  separate(boxes);
  return new Map(nodes.map((nd, i) => [nd.id, boxes[i]]));
}

/** Push overlapping boxes apart (along the axis with the smaller overlap) until none touch. */
function separate(b: Pos[], gap = 8): void {
  for (let pass = 0; pass < 80; pass++) {
    let moved = false;
    for (let i = 0; i < b.length; i++) for (let j = i + 1; j < b.length; j++) {
      const ox = Math.min(b[i].x + b[i].w, b[j].x + b[j].w) - Math.max(b[i].x, b[j].x) + gap;
      const oy = Math.min(b[i].y + b[i].h, b[j].y + b[j].h) - Math.max(b[i].y, b[j].y) + gap;
      if (ox <= 0 || oy <= 0) continue;
      moved = true;
      if (oy <= ox) { const d = (oy / 2 + 0.5) * (b[i].y <= b[j].y ? 1 : -1); b[i].y -= d; b[j].y += d; }
      else { const d = (ox / 2 + 0.5) * (b[i].x <= b[j].x ? 1 : -1); b[i].x -= d; b[j].x += d; }
    }
    if (!moved) return;
  }
}

export function clip(from: Pos, to: Pos): [number, number] {
  const cx = from.x + from.w / 2, cy = from.y + from.h / 2, tx = to.x + to.w / 2, ty = to.y + to.h / 2;
  const dx = tx - cx, dy = ty - cy;
  const s = Math.min(dx ? (to.w / 2 + 3) / Math.abs(dx) : Infinity, dy ? (to.h / 2 + 3) / Math.abs(dy) : Infinity);
  return [tx - dx * Math.min(s, 1), ty - dy * Math.min(s, 1)];
}

