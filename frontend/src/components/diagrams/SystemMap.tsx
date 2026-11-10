"use client";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Box, ExternalLink, Info } from "lucide-react";
import { api } from "@/lib/api";
import { useStats } from "@/hooks/queries";
import { useOpenFile } from "@/hooks/useOpen";
import { basename, cn } from "@/lib/utils";
import type { SgFile } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Badge } from "@/components/ui/badge";
import { clusterKeys } from "@/components/arch3d/layout3d";

/** System map at COMPONENT level: folders of code become boxes, grouped into role lanes (explicit rules shown on each lane), with one labelled arrow per pair of components.
 *  Files, functions and every individual import are one click deeper (side panel). Non-code files (JSON, Markdown, configs) are not part of the architecture drawing. */
const LANES = [
  { id: "entry", title: "Entry points", rule: "components holding the app entry (routes, main, app, index…)" },
  { id: "ui", title: "User interface", rule: "HTML/CSS/JSX/TSX components, or folders named components, screens, pages, views, ui" },
  { id: "logic", title: "Application logic", rule: "all other code folders (services, hooks, context, utils…)" },
  { id: "data", title: "Data & models", rule: "folders that define ORM / schema models, or are named models, db, schema" },
  { id: "ext", title: "External packages", rule: "third-party packages the code imports (standard library excluded)" },
  { id: "tests", title: "Tests", rule: "folders made only of test files" },
] as const;
type LaneId = (typeof LANES)[number]["id"];
const CODE = new Set(["python", "javascript", "typescript", "tsx", "jsx", "java", "go", "rust", "c", "cpp", "html", "css", "csharp", "kotlin", "ruby", "php"]);
const UI_LANG = new Set(["html", "css", "tsx", "jsx"]);
const STD = /^(typing|__future__|os|sys|re|json|time|pathlib|collections|dataclasses|datetime|math|logging|abc|functools|itertools|io|copy|enum|random|string|subprocess|threading|uuid|hashlib|base64|shutil|tempfile|glob|urllib|http|socket|asyncio|contextlib|traceback|warnings|inspect|operator|heapq|bisect|textwrap|csv|sqlite3|argparse|platform|queue|struct|zipfile|statistics|decimal|secrets|fnmatch|unittest|fs|path|crypto|stream|events|util|child_process|node:.*)$/;
const BW = 236, BH = 104, GX = 30, GY = 34, PER_ROW = 3, PAD = 20, HEAD = 34, TOP_LINKS = 14;

interface Comp { id: string; label: string; lane: LaneId; files: SgFile[]; lines: number; top: string[]; x: number; y: number; kind: "comp" | "pkg" }
interface Link { a: Comp; b: Comp; label: string; n: number; verified: boolean }

export function SystemMap({ repoId }: { repoId: string }) {
  const openFile = useOpenFile();
  const q = useQuery({ queryKey: ["system-graph", repoId], queryFn: () => api.graphSystem(repoId) });
  const stats = useStats(repoId);
  const [sel, setSel] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const g = q.data;

  const model = useMemo(() => {
    if (!g) return null;
    const code = g.files.filter((f) => CODE.has(f.language) || f.is_test);
    if (!code.length) return null;
    const keys = clusterKeys(code);
    const modelFiles = new Set((stats.data?.models ?? []).map((m) => m.file));
    const deg = new Map<string, number>();
    for (const e of g.edges) { if (e.type === "call" || e.type === "inherit") continue; deg.set(e.source, (deg.get(e.source) ?? 0) + 1); deg.set(e.target, (deg.get(e.target) ?? 0) + 1); }
    const groups = new Map<string, SgFile[]>();
    for (const f of code) groups.set(keys.get(f.id)!, [...(groups.get(keys.get(f.id)!) ?? []), f]);
    const laneOf = (id: string, fs: SgFile[]): LaneId => {
      if (fs.every((f) => f.is_test)) return "tests";
      if (fs.some((f) => f.entry)) return "entry";
      if (fs.some((f) => modelFiles.has(f.id)) || /(^|\/)(models?|db|schema|entities|database)(\/|$)/i.test(id)) return "data";
      const ui = fs.filter((f) => UI_LANG.has(f.language) || /\.(jsx|tsx)$/.test(f.id)).length;
      if (ui > fs.length / 2 || /(^|\/)(components?|screens?|pages?|views?|ui|templates?|static|public)(\/|$)/i.test(id)) return "ui";
      return "logic";
    };
    const comps: Comp[] = [];
    const lanes: { id: LaneId; title: string; rule: string; y: number; h: number }[] = [];
    let y = PAD;
    const placed = new Map<LaneId, Comp[]>();
    for (const [id, fs] of [...groups.entries()].sort((a, b) => b[1].length - a[1].length)) {
      const lane = laneOf(id, fs);
      const top = [...fs].sort((a, b) => (deg.get(b.id) ?? 0) - (deg.get(a.id) ?? 0)).slice(0, 3).map((f) => basename(f.id));
      placed.set(lane, [...(placed.get(lane) ?? []), { id, label: id === "(root)" ? "(project root)" : id, lane, files: fs, lines: fs.reduce((a, f) => a + f.lines, 0), top, x: 0, y: 0, kind: "comp" }]);
    }
    // external packages
    const ext = new Map<string, Set<string>>();
    for (const f of code) if (!f.is_test) for (const x of f.external) if (!STD.test(x) && !x.startsWith(".")) { const key = keys.get(f.id)!; ext.set(x, (ext.get(x) ?? new Set()).add(key)); }
    const pkgs = [...ext.entries()].sort((a, b) => b[1].size - a[1].size).slice(0, 8).map(([n, users]) => ({ id: `pkg:${n}`, label: n, lane: "ext" as LaneId, files: [] as SgFile[], lines: 0, top: [`used in ${users.size} component${users.size > 1 ? "s" : ""}`], x: 0, y: 0, kind: "pkg" as const }));
    if (pkgs.length) placed.set("ext", pkgs);
    for (const lane of LANES) {
      const list = placed.get(lane.id);
      if (!list?.length) continue;
      const rows = Math.ceil(list.length / PER_ROW);
      const h = HEAD + rows * (BH + GY);
      list.forEach((c, i) => { c.x = PAD + 16 + (i % PER_ROW) * (BW + GX); c.y = y + HEAD + Math.floor(i / PER_ROW) * (BH + GY); comps.push(c); });
      lanes.push({ id: lane.id, title: lane.title, rule: lane.rule, y, h });
      y += h + 12;
    }
    const byId = new Map(comps.map((c) => [c.id, c]));
    const agg = new Map<string, { n: number; names: string[]; verified: boolean }>();
    const add = (a: string, b: string, label: string | undefined, verified: boolean) => {
      if (a === b) return;
      const k = `${a}\u0000${b}`; const cur = agg.get(k) ?? { n: 0, names: [], verified: true };
      cur.n++; if (label) for (const x of label.split(", ")) if (x && !cur.names.includes(x) && cur.names.length < 3) cur.names.push(x.replace("…", ""));
      cur.verified = cur.verified && verified; agg.set(k, cur);
    };
    for (const e of g.edges) {
      if (e.type === "call" || e.type === "inherit") continue;
      const a = keys.get(e.source), b = keys.get(e.target); if (!a || !b) continue;
      add(a, b, e.label, e.verified);
    }
    for (const [k, users] of ext) if (byId.has(`pkg:${k}`)) for (const u of users) add(u, `pkg:${k}`, "", true);
    const links: Link[] = [];
    for (const [k, v] of agg) {
      const [a, b] = k.split("\u0000"); const ca = byId.get(a), cb = byId.get(b); if (!ca || !cb) continue;
      links.push({ a: ca, b: cb, label: cb.kind === "pkg" ? "uses" : v.names.length ? v.names.join(", ") : `${v.n} link${v.n > 1 ? "s" : ""}`, n: v.n, verified: v.verified });
    }
    links.sort((x, y2) => y2.n - x.n);
    return { comps, lanes, links, width: PAD * 2 + 32 + PER_ROW * (BW + GX) - GX, height: y + 8, dropped: g.files.length - code.length };
  }, [g, stats.data]);

  if (q.isLoading) return <div className="p-10"><Skeleton className="h-96" /></div>;
  if (q.isError) return <div className="p-10"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  if (!model || !model.comps.length) return <EmptyState className="h-full" icon={<Box className="size-5" />} title="No code to map yet" description="No parsed source files were found. JSON, Markdown and config files are not part of the architecture drawing." />;
  const selComp = model.comps.find((c) => c.id === sel);
  const touches = (l: Link, id: string) => l.a.id === id || l.b.id === id;
  const labelled = new Set(model.links.slice(0, 7).map((l) => l));

  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-auto bg-surface/30 p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Info className="size-3.5 shrink-0" /><span>Each box is a folder of code. Arrows show what one folder imports or calls from another, labelled with the names that cross. Click a box for its files and connections.</span>
          <Badge variant="outline">{model.comps.filter((c) => c.kind === "comp").length} components · {sel || showAll ? model.links.length : Math.min(TOP_LINKS, model.links.length)} of {model.links.length} links shown</Badge>
          {model.links.length > TOP_LINKS && !sel && <button onClick={() => setShowAll(!showAll)} className="text-xs font-medium text-primary hover:underline">{showAll ? "Show only the strongest links" : `Show all ${model.links.length} links`}</button>}
          {model.dropped > 0 && <Badge variant="outline" title="JSON, Markdown, YAML and other non-code files">{model.dropped} non-code files not drawn</Badge>}
        </div>
        <svg viewBox={`0 0 ${model.width} ${model.height}`} width="100%" style={{ maxWidth: model.width * 1.25 }} role="img" aria-label="Architecture of the project: components and the links between them">
          <defs>
            <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0L10 5L0 10z" className="fill-muted-foreground" /></marker>
            <marker id="arr-hi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto"><path d="M0 0L10 5L0 10z" className="fill-primary" /></marker>
          </defs>
          {model.lanes.map((l) => (
            <g key={l.id}>
              <rect x={PAD / 2} y={l.y} width={model.width - PAD} height={l.h} rx={14} className="fill-panel stroke-border" />
              <text x={PAD + 6} y={l.y + 22} className="fill-foreground text-[13px] font-semibold">{l.title}</text>
              <text x={PAD + 14 + l.title.length * 7.8} y={l.y + 22} className="fill-muted-foreground text-[11px]">{l.rule}</text>
            </g>
          ))}
          {(sel || showAll ? model.links : model.links.slice(0, TOP_LINKS)).map((l, i) => {
            const hi = sel && touches(l, sel), dim = sel && !hi;
            const down = l.a.y <= l.b.y;
            const same = l.a.y === l.b.y;
            const sx = l.a.x + BW / 2, sy = same ? l.a.y + BH / 2 : down ? l.a.y + BH : l.a.y;
            const tx = same ? (l.b.x > l.a.x ? l.b.x : l.b.x + BW) : l.b.x + BW / 2, ty = same ? l.b.y + BH / 2 : down ? l.b.y : l.b.y + BH;
            const sx2 = same ? (l.b.x > l.a.x ? l.a.x + BW : l.a.x) : sx;
            const my = (sy + ty) / 2, mx = (sx2 + tx) / 2;
            const d = same ? `M${sx2},${sy} C${(sx2 + tx) / 2},${sy - 46} ${(sx2 + tx) / 2},${ty - 46} ${tx},${ty}` : `M${sx2},${sy} C${sx2},${my} ${tx},${my} ${tx},${ty}`;
            const showLabel = hi || (!sel && labelled.has(l));
            const label = l.label.length > 30 ? l.label.slice(0, 29) + "…" : l.label;
            return (
              <g key={i} opacity={dim ? 0.07 : 1}>
                <path d={d} fill="none" strokeWidth={hi ? 2.4 : Math.min(3, 1 + l.n * 0.2)} strokeDasharray={l.verified ? undefined : "5 4"} markerEnd={hi ? "url(#arr-hi)" : "url(#arr)"} className={hi ? "stroke-primary" : "stroke-muted-foreground/55"} />
                {showLabel && <g><rect x={mx - label.length * 3.4 - 7} y={my - 10 - (same ? 24 : 0)} width={label.length * 6.8 + 14} height={19} rx={5} className="fill-panel stroke-border" /><text x={mx} y={my + 3.5 - (same ? 24 : 0)} textAnchor="middle" className={cn("text-[11px]", hi ? "fill-primary font-medium" : "fill-foreground")}>{label}</text></g>}
              </g>
            );
          })}
          {model.comps.map((c) => {
            const dim = sel && sel !== c.id && !model.links.some((l) => touches(l, sel) && touches(l, c.id));
            return (
              <g key={c.id} opacity={dim ? 0.3 : 1} className="cursor-pointer" onClick={() => setSel((s) => (s === c.id ? null : c.id))}>
                {c.kind === "pkg" ? <polygon points={`${c.x + 18},${c.y} ${c.x + BW - 18},${c.y} ${c.x + BW},${c.y + BH / 2} ${c.x + BW - 18},${c.y + BH} ${c.x + 18},${c.y + BH} ${c.x},${c.y + BH / 2}`} className={cn("fill-panel", sel === c.id ? "stroke-primary" : "stroke-border")} strokeWidth={sel === c.id ? 2.4 : 1.3} />
                  : <rect x={c.x} y={c.y} width={BW} height={BH} rx={10} className={cn("fill-panel", sel === c.id ? "stroke-primary" : c.lane === "entry" ? "stroke-warning" : c.lane === "tests" ? "stroke-success" : "stroke-border")} strokeWidth={sel === c.id ? 2.4 : 1.4} />}
                <text x={c.x + BW / 2} y={c.y + 27} textAnchor="middle" className="fill-foreground text-[14px] font-semibold">{c.label.length > 26 ? "…" + c.label.slice(-25) : c.label}</text>
                {c.kind === "comp" && <text x={c.x + BW / 2} y={c.y + 46} textAnchor="middle" className="fill-muted-foreground text-[11px]">{c.files.length} file{c.files.length === 1 ? "" : "s"} · {c.lines.toLocaleString()} lines</text>}
                {c.top.map((t, i) => <text key={i} x={c.x + BW / 2} y={c.y + (c.kind === "comp" ? 64 : 52) + i * 14} textAnchor="middle" className="fill-muted-foreground/90 text-[10.5px] font-mono">{t.length > 30 ? t.slice(0, 29) + "…" : t}</text>)}
              </g>
            );
          })}
        </svg>
      </div>
      <aside className="hidden w-80 shrink-0 overflow-y-auto border-l bg-panel p-4 md:block">
        {selComp ? (
          <div className="space-y-3 text-[13px]">
            <div><div className="text-sm font-semibold">{selComp.label}</div><div className="text-[11px] text-muted-foreground">{selComp.kind === "pkg" ? "external package" : `${selComp.files.length} files · ${LANES.find((l) => l.id === selComp.lane)?.title}`}</div></div>
            <div className="space-y-1">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Connections</div>
              {model.links.filter((l) => touches(l, selComp.id)).map((l, i) => { const out = l.a.id === selComp.id; const other = out ? l.b : l.a;
                return <button key={i} onClick={() => setSel(other.id)} className="block w-full rounded-md px-1.5 py-1 text-left text-xs hover:bg-accent/60"><span className={out ? "text-info" : "text-warning"}>{out ? "→ uses" : "← used by"}</span> <span className="font-medium">{other.label}</span><span className="block pl-3 text-[11px] text-muted-foreground">{l.label}{l.verified ? "" : " (inferred)"}</span></button>; })}
              {model.links.filter((l) => touches(l, selComp.id)).length === 0 && <p className="text-xs text-muted-foreground">No links to other components.</p>}
            </div>
            {selComp.files.length > 0 && <div>
              <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Files</div>
              <ul>{selComp.files.slice(0, 40).map((f) => <li key={f.id}><button onClick={() => openFile(f.id)} className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left font-mono text-[12px] hover:bg-accent/60"><span className="truncate">{basename(f.id)}</span>{f.entry && <Badge variant="warning">entry</Badge>}<span className="ml-auto text-[11px] text-muted-foreground">{f.lines} ln</span></button></li>)}</ul>
              {selComp.files.length > 40 && <p className="px-1.5 text-[11px] text-muted-foreground">+{selComp.files.length - 40} more in the File structure view</p>}
              <button onClick={() => openFile(selComp.files[0].id)} className="mt-2 inline-flex items-center gap-1.5 text-xs text-primary hover:underline"><ExternalLink className="size-3.5" />Open in Code Explorer</button>
            </div>}
          </div>
        ) : <p className="text-xs leading-relaxed text-muted-foreground">Select a box to see its files and exactly what it connects to. Orange outline = holds an entry point, green = tests, hexagon = external package, dashed arrow = inferred (name match).</p>}
      </aside>
    </div>
  );
}
