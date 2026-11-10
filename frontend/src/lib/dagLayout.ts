/** Layered (top-to-bottom) layout for dependency graphs. Nodes NEVER overlap: every node gets its own slot in a row, rows are spaced apart, wide rows wrap into several rows.
 *  Layers come from the dependency direction (importers above what they import); cycles are broken by ignoring back edges; the order inside each layer is improved with
 *  barycenter sweeps so that fewer lines cross. Deterministic. */
export interface DagNode { id: string; w: number; h: number; label: string }
export interface DagEdge { source: string; target: string }
export interface DagPos { x: number; y: number; w: number; h: number; layer: number }

export function dagLayout(nodes: DagNode[], edges: DagEdge[], opts: { gapX?: number; gapY?: number; maxRow?: number } = {}): Map<string, DagPos> {
  const gapX = opts.gapX ?? 44, gapY = opts.gapY ?? 84, maxRow = opts.maxRow ?? 7;
  const ids = new Set(nodes.map((n) => n.id));
  const out = new Map<string, string[]>(), inc = new Map<string, string[]>();
  for (const n of nodes) { out.set(n.id, []); inc.set(n.id, []); }
  const seenEdge = new Set<string>();
  for (const e of edges) {
    if (e.source === e.target || !ids.has(e.source) || !ids.has(e.target)) continue;
    const k = `${e.source}\u0000${e.target}`; if (seenEdge.has(k)) continue; seenEdge.add(k);
    out.get(e.source)!.push(e.target); inc.get(e.target)!.push(e.source);
  }
  // break cycles: iterative DFS, edges that point back into the current path are ignored
  const state = new Map<string, 0 | 1 | 2>(); const back = new Set<string>();
  const order = [...nodes].sort((a, b) => (inc.get(a.id)!.length - inc.get(b.id)!.length) || a.label.localeCompare(b.label));
  for (const root of order) {
    if (state.get(root.id)) continue;
    const stack: [string, number][] = [[root.id, 0]]; state.set(root.id, 1);
    while (stack.length) {
      const top = stack[stack.length - 1]; const [v, i] = top; const ts = out.get(v)!;
      if (i >= ts.length) { state.set(v, 2); stack.pop(); continue; }
      top[1]++;
      const t = ts[i]; const st = state.get(t);
      if (st === 1) back.add(`${v}\u0000${t}`);
      else if (!st) { state.set(t, 1); stack.push([t, 0]); }
    }
  }
  const dagOut = new Map<string, string[]>(); const dagIn = new Map<string, string[]>();
  for (const n of nodes) { dagOut.set(n.id, []); dagIn.set(n.id, []); }
  for (const [s, ts] of out) for (const t of ts) if (!back.has(`${s}\u0000${t}`)) { dagOut.get(s)!.push(t); dagIn.get(t)!.push(s); }
  // longest-path layering
  const layer = new Map<string, number>();
  const indeg = new Map(nodes.map((n) => [n.id, dagIn.get(n.id)!.length])); const queue = nodes.filter((n) => indeg.get(n.id) === 0).map((n) => n.id);
  for (const q of queue) layer.set(q, 0);
  for (let qi = 0; qi < queue.length; qi++) {
    const v = queue[qi];
    for (const t of dagOut.get(v)!) { layer.set(t, Math.max(layer.get(t) ?? 0, (layer.get(v) ?? 0) + 1)); indeg.set(t, indeg.get(t)! - 1); if (indeg.get(t) === 0) queue.push(t); }
  }
  for (const n of nodes) if (!layer.has(n.id)) layer.set(n.id, 0);
  const maxLayer = Math.max(0, ...layer.values());
  const rows: string[][] = Array.from({ length: maxLayer + 1 }, () => []);
  for (const n of [...nodes].sort((a, b) => a.label.localeCompare(b.label))) rows[layer.get(n.id)!].push(n.id);
  // barycenter sweeps
  const pos = new Map<string, number>();
  const reindex = () => rows.forEach((r) => r.forEach((id, i) => pos.set(id, i)));
  reindex();
  const bary = (id: string, nb: string[]) => (nb.length ? nb.reduce((a, x) => a + (pos.get(x) ?? 0), 0) / nb.length : pos.get(id) ?? 0);
  for (let sweep = 0; sweep < 6; sweep++) {
    const down = sweep % 2 === 0;
    const idxs = down ? rows.map((_, i) => i).slice(1) : rows.map((_, i) => i).slice(0, -1).reverse();
    for (const li of idxs) {
      const nbOf = (id: string) => (down ? dagIn.get(id)! : dagOut.get(id)!);
      rows[li] = rows[li].map((id) => ({ id, b: bary(id, nbOf(id)) })).sort((a, b) => a.b - b.b || a.id.localeCompare(b.id)).map((x) => x.id);
      rows[li].forEach((id, i) => pos.set(id, i));
    }
  }
  // positions: wide layers wrap into several rows; every row is centred
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const res = new Map<string, DagPos>();
  let y = 0;
  rows.forEach((r, li) => {
    for (let s = 0; s < r.length; s += maxRow) {
      const chunk = r.slice(s, s + maxRow);
      const total = chunk.reduce((a, id) => a + byId.get(id)!.w, 0) + gapX * (chunk.length - 1);
      let x = -total / 2;
      const rowH = Math.max(...chunk.map((id) => byId.get(id)!.h));
      for (const id of chunk) { const n = byId.get(id)!; res.set(id, { x, y, w: n.w, h: n.h, layer: li }); x += n.w + gapX; }
      y += rowH + gapY;
    }
  });
  return res;
}
