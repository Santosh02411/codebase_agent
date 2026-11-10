"use client";
import { useMemo, useState } from "react";
import { Braces, ChevronRight, File, FileCode2, FileJson, FileText, Folder, FolderOpen, Search, X } from "lucide-react";
import { useGitStatus, useTree } from "@/hooks/queries";
import { basename, cn, fuzzy } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";

interface Node { name: string; path: string; dir: boolean; children: Node[] }

function build(files: string[]): Node {
  const root: Node = { name: "", path: "", dir: true, children: [] };
  for (const f of files) {
    let cur = root;
    const parts = f.split("/");
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join("/");
      let next = cur.children.find((c) => c.name === part);
      if (!next) { next = { name: part, path, dir: i < parts.length - 1, children: [] }; cur.children.push(next); }
      cur = next;
    });
  }
  const sort = (n: Node) => { n.children.sort((a, b) => Number(b.dir) - Number(a.dir) || a.name.localeCompare(b.name)); n.children.forEach(sort); };
  sort(root);
  return root;
}

export function FileGlyph({ name, className }: { name: string; className?: string }) {
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
  const c = cn("size-3.5 shrink-0", className);
  if (["py", "js", "jsx", "ts", "tsx", "java", "go", "rs", "c", "cpp", "h", "cs", "rb", "php", "kt"].includes(ext)) return <FileCode2 className={cn(c, "text-info")} />;
  if (["json", "yml", "yaml", "toml"].includes(ext)) return <FileJson className={cn(c, "text-warning")} />;
  if (["md", "txt", "rst"].includes(ext)) return <FileText className={cn(c, "text-muted-foreground")} />;
  if (["css", "html", "sql"].includes(ext)) return <Braces className={cn(c, "text-chart-5")} />;
  return <File className={cn(c, "text-muted-foreground")} />;
}

const GIT_TONE: Record<string, string> = { modified: "text-warning", added: "text-success", untracked: "text-success", deleted: "text-destructive" };
const GIT_LETTER: Record<string, string> = { modified: "M", added: "A", untracked: "U", deleted: "D" };

export function FileTree({ repoId, selected, onOpen }: { repoId: string; selected?: string; onOpen: (path: string) => void }) {
  const tree = useTree(repoId);
  const git = useGitStatus(repoId);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const changed = useMemo(() => new Map((git.data?.files ?? []).map((f) => [f.path, f.status])), [git.data]);
  const root = useMemo(() => build(tree.data ?? []), [tree.data]);
  const hits = useMemo(() => q ? (tree.data ?? []).map((f) => ({ f, s: Math.max(fuzzy(q, basename(f)) + 2, fuzzy(q, f)) })).filter((x) => x.s >= 0).sort((a, b) => b.s - a.s).slice(0, 200).map((x) => x.f) : [], [q, tree.data]);

  // keep the folders that contain the open file expanded
  const expanded = useMemo(() => {
    const s = new Set(open);
    if (selected) { const p = selected.split("/"); for (let i = 1; i < p.length; i++) s.add(p.slice(0, i).join("/")); }
    return s;
  }, [open, selected]);
  const toggle = (p: string) => setOpen((o) => { const n = new Set(o); if (n.has(p)) n.delete(p); else n.add(p); return n; });

  const row = (n: Node, depth: number): React.ReactNode => {
    const isOpen = expanded.has(n.path);
    const git_ = changed.get(n.path);
    return (
      <li key={n.path} role="none">
        <button role="treeitem" aria-expanded={n.dir ? isOpen : undefined} aria-selected={selected === n.path} onClick={() => (n.dir ? toggle(n.path) : onOpen(n.path))} style={{ paddingLeft: 8 + depth * 14 }}
          className={cn("flex w-full items-center gap-1.5 rounded-md py-[3px] pr-2 text-left text-[13px] hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60", selected === n.path && "bg-accent font-medium")}>
          {n.dir ? <><ChevronRight className={cn("size-3 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-90")} />{isOpen ? <FolderOpen className="size-3.5 shrink-0 text-primary/80" /> : <Folder className="size-3.5 shrink-0 text-primary/80" />}</> : <><span className="w-3 shrink-0" /><FileGlyph name={n.name} /></>}
          <span className={cn("truncate", git_ && GIT_TONE[git_])}>{n.name}</span>
          {git_ && <span className={cn("ml-auto text-[10px] font-semibold", GIT_TONE[git_])} title={git_}>{GIT_LETTER[git_]}</span>}
        </button>
        {n.dir && isOpen && <ul role="group">{n.children.map((c) => row(c, depth + 1))}</ul>}
      </li>
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative shrink-0 p-2">
        <Search className="pointer-events-none absolute left-4 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter files…" aria-label="Filter files" className="h-8 pl-8 pr-7" />
        {q && <button aria-label="Clear filter" className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setQ("")}><X className="size-3.5" /></button>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-3">
        {tree.isLoading ? <div className="space-y-1.5 p-1">{Array.from({ length: 10 }, (_, i) => <Skeleton key={i} className="h-5" />)}</div>
          : tree.isError ? <ErrorState title="Couldn’t load files" error={tree.error} onRetry={() => tree.refetch()} className="m-2" />
          : q ? (hits.length === 0 ? <div className="px-3 py-6 text-center text-xs text-muted-foreground">No files match “{q}”.</div> :
              <ul role="tree" aria-label="Matching files">{hits.map((f) => <li key={f} role="none"><button role="treeitem" aria-selected={selected === f} onClick={() => onOpen(f)} className={cn("flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-[13px] hover:bg-accent/60", selected === f && "bg-accent")}><FileGlyph name={basename(f)} /><span className="truncate">{basename(f)}</span><span className="ml-auto max-w-[50%] truncate text-[11px] text-muted-foreground">{f.includes("/") ? f.slice(0, f.lastIndexOf("/")) : ""}</span></button></li>)}</ul>)
          : <ul role="tree" aria-label="Files">{root.children.map((c) => row(c, 0))}</ul>}
      </div>
    </div>
  );
}
