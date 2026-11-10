import type { SgEdge, SgFile, SgSymbol, SystemGraph } from "@/lib/types";

export interface Cluster { id: string; label: string; files: string[]; x: number; y: number; z: number; radius: number; languages: Record<string, number>; entries: number; tests: number }
export interface FileNode { id: string; file: SgFile; cluster: string; x: number; y: number; z: number; r: number }
export interface SymNode { id: string; sym: SgSymbol; x: number; y: number; z: number; r: number }
export interface Layout { clusters: Cluster[]; clusterOf: Map<string, string>; files: Map<string, FileNode>; symbolsByFile: Map<string, SgSymbol[]> }

function rng(seed: number) { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const hash = (s: string) => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
const fib = (i: number, n: number): [number, number, number] => { const y = n === 1 ? 0 : 1 - (i / (n - 1)) * 2; const r = Math.sqrt(Math.max(0, 1 - y * y)); const t = Math.PI * (3 - Math.sqrt(5)) * i; return [Math.cos(t) * r, y, Math.sin(t) * r]; };

/** Group files by directory, using the shallowest depth that gives a useful number of groups. */
export function clusterKeys(files: SgFile[]): Map<string, string> {
  const key = (p: string, d: number) => { const seg = p.split("/").slice(0, -1); return seg.length ? seg.slice(0, d).join("/") : "(root)"; };
  let depth = 1;
  for (; depth <= 3; depth++) if (new Set(files.map((f) => key(f.id, depth))).size >= 4) break;
  return new Map(files.map((f) => [f.id, key(f.id, Math.min(depth, 3))]));
}

/** 3D layout from the real graph: clusters (folders) are pulled together by the imports/calls/tests between them, files sit inside their cluster. Deterministic. */
export function layoutSystem(g: SystemGraph): Layout {
  const clusterOf = clusterKeys(g.files);
  const byCluster = new Map<string, SgFile[]>();
  for (const f of g.files) byCluster.set(clusterOf.get(f.id)!, [...(byCluster.get(clusterOf.get(f.id)!) ?? []), f]);
  const ids = [...byCluster.keys()].sort();
  const radius = (n: number) => 1.7 + Math.cbrt(n) * 1.25;
  const idx = new Map(ids.map((id, i) => [id, i]));
  const R = ids.map((id) => radius(byCluster.get(id)!.length));
  const P = ids.map((id, i) => { const [x, y, z] = fib(i, ids.length); const s = 9 + Math.sqrt(g.files.length) * 1.6; return [x * s, y * s, z * s]; });
  // aggregated links between clusters
  const links = new Map<string, number>();
  for (const e of g.edges) {
    if (e.type === "call" || e.type === "inherit") continue;
    const a = clusterOf.get(e.source), b = clusterOf.get(e.target);
    if (!a || !b || a === b) continue;
    const k = idx.get(a)! < idx.get(b)! ? `${a}\u0000${b}` : `${b}\u0000${a}`;
    links.set(k, (links.get(k) ?? 0) + (e.verified ? 1 : 0.5) * Math.min(3, e.weight));
  }
  const V = ids.map(() => [0, 0, 0]);
  for (let it = 0; it < 220; it++) {
    const cool = 1 - it / 260;
    for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
      const dx = P[i][0] - P[j][0], dy = P[i][1] - P[j][1], dz = P[i][2] - P[j][2];
      const d2 = dx * dx + dy * dy + dz * dz + 0.01, d = Math.sqrt(d2), min = R[i] + R[j] + 3;
      const f = (min * min * 1.6) / d2;
      for (let a = 0; a < 3; a++) { const dir = [dx, dy, dz][a] / d; V[i][a] += dir * f; V[j][a] -= dir * f; }
    }
    for (const [k, w] of links) {
      const [a, b] = k.split("\u0000"); const i = idx.get(a)!, j = idx.get(b)!;
      const dx = P[j][0] - P[i][0], dy = P[j][1] - P[i][1], dz = P[j][2] - P[i][2], d = Math.sqrt(dx * dx + dy * dy + dz * dz) + 0.01;
      const rest = R[i] + R[j] + 5, f = 0.035 * Math.sqrt(w) * (d - rest);
      for (let c = 0; c < 3; c++) { const dir = [dx, dy, dz][c] / d; V[i][c] += dir * f; V[j][c] -= dir * f; }
    }
    for (let i = 0; i < ids.length; i++) for (let a = 0; a < 3; a++) { V[i][a] += -P[i][a] * 0.012; P[i][a] += Math.max(-2, Math.min(2, V[i][a])) * cool; V[i][a] *= 0.6; }
  }
  const clusters: Cluster[] = ids.map((id, i) => {
    const fs = byCluster.get(id)!; const langs: Record<string, number> = {};
    fs.forEach((f) => { langs[f.language || "other"] = (langs[f.language || "other"] ?? 0) + 1; });
    return { id, label: id, files: fs.map((f) => f.id), x: P[i][0], y: P[i][1], z: P[i][2], radius: R[i], languages: langs, entries: fs.filter((f) => f.entry).length, tests: fs.filter((f) => f.is_test).length };
  });
  // files inside each cluster
  const files = new Map<string, FileNode>();
  const intra = new Map<string, string[]>();
  for (const e of g.edges) if (e.type !== "call" && e.type !== "inherit" && clusterOf.get(e.source) === clusterOf.get(e.target)) intra.set(e.source, [...(intra.get(e.source) ?? []), e.target]);
  for (const c of clusters) {
    const fs = byCluster.get(c.id)!.slice().sort((a, b) => a.id.localeCompare(b.id));
    const n = fs.length; const rand = rng(hash(c.id));
    const pos = fs.map((_, i) => { const [x, y, z] = fib(i, n); const r = c.radius * 0.8; return [x * r + (rand() - 0.5) * 0.3, y * r + (rand() - 0.5) * 0.3, z * r + (rand() - 0.5) * 0.3]; });
    const at = new Map(fs.map((f, i) => [f.id, i]));
    for (let it = 0; it < 70; it++) {
      const acc = pos.map(() => [0, 0, 0]);
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
        const dx = pos[i][0] - pos[j][0], dy = pos[i][1] - pos[j][1], dz = pos[i][2] - pos[j][2], d2 = dx * dx + dy * dy + dz * dz + 0.01, d = Math.sqrt(d2), f = 1.4 / d2;
        for (let a = 0; a < 3; a++) { const dir = [dx, dy, dz][a] / d; acc[i][a] += dir * f; acc[j][a] -= dir * f; }
      }
      for (const [s, ts] of intra) { const i = at.get(s); if (i === undefined) continue; for (const t of ts) { const j = at.get(t); if (j === undefined) continue;
        const dx = pos[j][0] - pos[i][0], dy = pos[j][1] - pos[i][1], dz = pos[j][2] - pos[i][2], d = Math.sqrt(dx * dx + dy * dy + dz * dz) + 0.01, f = 0.04 * (d - 1.6);
        for (let a = 0; a < 3; a++) { const dir = [dx, dy, dz][a] / d; acc[i][a] += dir * f; acc[j][a] -= dir * f; } } }
      for (let i = 0; i < n; i++) { for (let a = 0; a < 3; a++) pos[i][a] += Math.max(-0.4, Math.min(0.4, acc[i][a])) * (1 - it / 90); const len = Math.hypot(pos[i][0], pos[i][1], pos[i][2]); const max = c.radius * 0.92; if (len > max) for (let a = 0; a < 3; a++) pos[i][a] *= max / len; }
    }
    fs.forEach((f, i) => files.set(f.id, { id: f.id, file: f, cluster: c.id, x: c.x + pos[i][0], y: c.y + pos[i][1], z: c.z + pos[i][2], r: Math.max(0.24, Math.min(0.6, 0.2 + 0.035 * Math.log2(f.lines + 2))) }));
  }
  const symbolsByFile = new Map<string, SgSymbol[]>();
  for (const s of g.symbols) symbolsByFile.set(s.file, [...(symbolsByFile.get(s.file) ?? []), s]);
  return { clusters, clusterOf, files, symbolsByFile };
}

/** Symbols orbit their file. Computed on demand, only for files whose symbols are shown. */
export function symbolPositions(layout: Layout, fileIds: Iterable<string>): Map<string, SymNode> {
  const out = new Map<string, SymNode>();
  for (const fid of fileIds) {
    const fn = layout.files.get(fid); const syms = layout.symbolsByFile.get(fid);
    if (!fn || !syms) continue;
    const n = syms.length; const orbit = 0.85 + Math.cbrt(n) * 0.2;
    syms.forEach((s, i) => { const [x, y, z] = fib(i, n); out.set(s.id, { id: s.id, sym: s, x: fn.x + x * orbit, y: fn.y + y * orbit, z: fn.z + z * orbit, r: s.route ? 0.17 : s.kind === "class" ? 0.15 : 0.11 }); });
  }
  return out;
}

export const LANG_HUE: Record<string, number> = { python: 212, javascript: 48, typescript: 205, java: 18, go: 186, rust: 24, c: 260, cpp: 270, csharp: 280, ruby: 350, php: 240, kotlin: 290, markdown: 150, json: 90, yaml: 120, html: 8, css: 320, sql: 170 };
export const hsl = (h: number, s = 68, l = 58) => `hsl(${h % 360} ${s}% ${l}%)`;
export const clusterColor = (i: number) => hsl(i * 47 + 205);
export const langColor = (lang: string) => hsl(LANG_HUE[lang] ?? 215 + (hash(lang || "x") % 120), 62, 58);

export interface Adjacency { out: Map<string, SgEdge[]>; inc: Map<string, SgEdge[]> }
export function adjacency(edges: SgEdge[]): Adjacency {
  const out = new Map<string, SgEdge[]>(), inc = new Map<string, SgEdge[]>();
  for (const e of edges) { out.set(e.source, [...(out.get(e.source) ?? []), e]); inc.set(e.target, [...(inc.get(e.target) ?? []), e]); }
  return { out, inc };
}

/** Shortest path over the parsed relationships (breadth-first). `undirected` also walks edges backwards. Returns the edges of the path, or null. */
export function tracePath(adj: Adjacency, from: string, to: string, allow: (e: SgEdge) => boolean, undirected: boolean): SgEdge[] | null {
  if (from === to) return [];
  const prev = new Map<string, { node: string; edge: SgEdge }>();
  const q = [from]; const seen = new Set([from]);
  while (q.length) {
    const cur = q.shift()!;
    const next: [string, SgEdge][] = [];
    for (const e of adj.out.get(cur) ?? []) if (allow(e)) next.push([e.target, e]);
    if (undirected) for (const e of adj.inc.get(cur) ?? []) if (allow(e)) next.push([e.source, e]);
    for (const [n, e] of next) {
      if (seen.has(n)) continue;
      seen.add(n); prev.set(n, { node: cur, edge: e });
      if (n === to) { const path: SgEdge[] = []; let c = to; while (c !== from) { const p = prev.get(c)!; path.unshift(p.edge); c = p.node; } return path; }
      q.push(n);
    }
  }
  return null;
}
