"use client";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, FlaskConical, Folder, FolderOpen, Search } from "lucide-react";
import { api } from "@/lib/api";
import { useOpenFile } from "@/hooks/useOpen";
import { cn, fuzzy } from "@/lib/utils";
import type { SgFile } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { FileGlyph } from "@/components/explorer/FileTree";
import { langColor } from "@/components/arch3d/layout3d";

interface Node { name: string; path: string; file?: SgFile; children: Node[]; files: number; langs: Map<string, number>; size?: number; plain?: boolean }
const ext = (n: string) => (n.includes(".") ? n.split(".").pop()! : "");
const kb = (b?: number) => (b == null ? "" : b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`);

/** The project's file structure, annotated with what the parser knows about each file. */
export function StructureTree({ repoId }: { repoId: string }) {
  const openFile = useOpenFile();
  const q = useQuery({ queryKey: ["system-graph", repoId], queryFn: () => api.graphSystem(repoId) });
  const all = useQuery({ queryKey: ["repo-files", repoId], queryFn: () => api.repoFiles(repoId) });
  const ins = useQuery({ queryKey: ["insights", repoId], queryFn: () => api.insights(repoId) });
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const untested = useMemo(() => new Set(ins.data?.risks.untested_modules ?? []), [ins.data]);
  const root = useMemo(() => {
    const r: Node = { name: "", path: "", children: [], files: 0, langs: new Map() };
    const info = new Map((q.data?.files ?? []).map((f) => [f.id, f]));
    const rows = (all.data?.files ?? []).map((f) => ({ id: f.path, size: f.size, f: info.get(f.path) }));
    for (const row of rows.length ? rows : (q.data?.files ?? []).map((f) => ({ id: f.id, size: 0, f }))) {
      const f = row.f as SgFile | undefined;
      let cur = r; const parts = row.id.split("/");
      cur.files++;
      parts.forEach((p, i) => {
        const path = parts.slice(0, i + 1).join("/");
        let n = cur.children.find((c) => c.name === p);
        if (!n) { n = { name: p, path, children: [], files: 0, langs: new Map(), file: i === parts.length - 1 ? (f ?? ({ id: row.id, name: p, folder: "", language: "", lines: 0, symbols: 0, is_test: false, tests: 0, routes: [], entry: null, imports: 0, imported_by: 0, external: [] } as SgFile)) : undefined, size: row.size, plain: i === parts.length - 1 && !f }; cur.children.push(n); }
        n.files++; n.langs.set((f?.language || ext(p)) || "other", (n.langs.get((f?.language || ext(p)) || "other") ?? 0) + 1);
        cur = n;
      });
    }
    const sort = (n: Node) => { n.children.sort((a, b) => Number(!!a.file) - Number(!!b.file) || a.name.localeCompare(b.name)); n.children.forEach(sort); };
    sort(r);
    return r;
  }, [q.data]);
  if (q.isLoading || all.isLoading) return <div className="p-8"><Skeleton className="h-96" /></div>;
  if (q.isError) return <div className="p-8"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  const match = (n: Node): boolean => (!filter ? true : fuzzy(filter, n.path) >= 0 || n.children.some(match));
  const row = (n: Node, depth: number): React.ReactNode => {
    if (!match(n)) return null;
    const isOpen = open.has(n.path) || !!filter;
    const f = n.file;
    return (
      <li key={n.path}>
        <div style={{ paddingLeft: 10 + depth * 18 }} className="group flex items-center gap-2 rounded-md py-[5px] pr-3 text-[13px] hover:bg-accent/50">
          {f ? <><span className="w-3.5" /><FileGlyph name={n.name} /></> : <button aria-label={isOpen ? "Collapse" : "Expand"} onClick={() => setOpen((s) => { const x = new Set(s); if (x.has(n.path)) x.delete(n.path); else x.add(n.path); return x; })} className="flex items-center gap-1.5"><ChevronRight className={cn("size-3.5 text-muted-foreground transition-transform", isOpen && "rotate-90")} />{isOpen ? <FolderOpen className="size-4 text-primary/80" /> : <Folder className="size-4 text-primary/80" />}</button>}
          <button onClick={() => (f ? openFile(f.id) : setOpen((s) => { const x = new Set(s); if (x.has(n.path)) x.delete(n.path); else x.add(n.path); return x; }))} className={cn("min-w-0 truncate text-left", f ? "font-mono" : "font-medium")}>{n.name}</button>
          {!f && <span className="text-xs text-muted-foreground">{n.files} file{n.files === 1 ? "" : "s"}</span>}
          {!f && <span className="flex gap-1">{[...n.langs.entries()].slice(0, 3).map(([l]) => <span key={l} title={l} className="size-2 rounded-full" style={{ background: langColor(l) }} />)}</span>}
          {f && <span className="ml-auto flex items-center gap-1.5">
            {f.entry && <Badge variant="warning">{f.entry === "route" ? "routes" : "entry"}</Badge>}
            {f.is_test && <Badge variant="success"><FlaskConical className="size-3" />test</Badge>}
            {!f.is_test && untested.has(f.id) && <Badge variant="outline" title="No test reaches this module">untested</Badge>}
            {f.symbols > 0 && <span className="w-20 text-right text-[11px] text-muted-foreground">{f.symbols} symbols</span>}
            <span className="w-16 text-right text-[11px] tabular-nums text-muted-foreground">{n.plain ? kb(n.size) : `${f.lines} ln`}</span>
            {f.imported_by > 0 && <span className="w-24 text-right text-[11px] text-muted-foreground" title="files that import this one">used by {f.imported_by}</span>}
          </span>}
        </div>
        {!f && isOpen && <ul>{n.children.map((c) => row(c, depth + 1))}</ul>}
      </li>
    );
  };
  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-5xl p-4">
        <div className="relative mb-3 max-w-sm"><Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" /><Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter the structure…" aria-label="Filter the file structure" className="pl-8" /></div>
        <div className="rounded-xl bg-panel py-2 shadow-card"><ul>{root.children.map((c) => row(c, 0))}</ul></div>
        {(all.data?.skipped_dirs.length ?? 0) > 0 && <p className="mt-2 text-xs text-muted-foreground">Not expanded: {all.data!.skipped_dirs.slice(0, 8).join(", ")}{all.data!.skipped_dirs.length > 8 ? "…" : ""} (dependency, build and cache folders).</p>}
        <p className="mt-3 text-xs text-muted-foreground">Every file of the project is listed. Badges come from the parser (routes/entry points, test files, modules no test reaches, symbol counts, how many files import each one) and only exist for code files.</p>
      </div>
    </div>
  );
}
