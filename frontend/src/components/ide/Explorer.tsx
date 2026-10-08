"use client";
import { useMemo, useState } from "react";
import { Braces, ChevronDown, ChevronRight, File, FileCode2, FileJson, FileText, Folder, FolderOpen, FunctionSquare, Box } from "lucide-react";
import { useFileSymbols, useGitStatus, useTree } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn, fuzzy } from "@/lib/utils";
import type { GitFile } from "@/lib/types";

interface Node { name: string; path: string; dir: boolean; children: Node[] }

function buildTree(files: string[]): Node {
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

export function FileIcon({ name, className }: { name: string; className?: string }) {
  const ext = name.split(".").pop()?.toLowerCase();
  const cls = cn("size-3.5 shrink-0", className);
  if (["py", "js", "jsx", "ts", "tsx", "go", "rs", "java", "c", "cpp", "sh"].includes(ext ?? "")) return <FileCode2 className={cn(cls, "text-sky-400")} />;
  if (["json", "yml", "yaml", "toml"].includes(ext ?? "")) return <FileJson className={cn(cls, "text-amber-400")} />;
  if (["md", "txt"].includes(ext ?? "")) return <FileText className={cn(cls, "text-slate-400")} />;
  return <File className={cn(cls, "text-slate-400")} />;
}

const STATUS_STYLE: Record<GitFile["status"], string> = { modified: "text-amber-400", added: "text-emerald-400", untracked: "text-emerald-400", deleted: "text-red-400" };
const STATUS_LETTER: Record<GitFile["status"], string> = { modified: "M", added: "A", untracked: "U", deleted: "D" };

function Row({ node, depth, open, toggle, active, status }: { node: Node; depth: number; open: Set<string>; toggle: (p: string) => void; active?: string; status: Map<string, GitFile>; }) {
  const openFile = useIde((s) => s.openFile);
  const isOpen = open.has(node.path);
  const st = status.get(node.path);
  // folders show a dot when anything inside changed
  const dirty = node.dir && [...status.keys()].some((k) => k.startsWith(node.path + "/"));
  return (
    <>
      <button
        onClick={() => (node.dir ? toggle(node.path) : openFile(node.path))}
        className={cn("flex h-6 w-full items-center gap-1 pr-2 text-left hover:bg-accent/60", active === node.path && "bg-accent text-accent-foreground")}
        style={{ paddingLeft: 8 + depth * 12 }}
        title={node.path}
      >
        {node.dir ? (isOpen ? <ChevronDown className="size-3 shrink-0 opacity-70" /> : <ChevronRight className="size-3 shrink-0 opacity-70" />) : <span className="w-3" />}
        {node.dir ? (isOpen ? <FolderOpen className="size-3.5 shrink-0 text-sky-300/80" /> : <Folder className="size-3.5 shrink-0 text-sky-300/80" />) : <FileIcon name={node.name} />}
        <span className={cn("truncate", st && STATUS_STYLE[st.status])}>{node.name}</span>
        {st && <span className={cn("ml-auto text-[10px] font-semibold", STATUS_STYLE[st.status])}>{STATUS_LETTER[st.status]}</span>}
        {dirty && <span className="ml-auto size-1.5 rounded-full bg-amber-400" />}
      </button>
      {node.dir && isOpen && node.children.map((c) => <Row key={c.path} node={c} depth={depth + 1} open={open} toggle={toggle} active={active} status={status} />)}
    </>
  );
}

const KIND_ICON: Record<string, React.ReactNode> = {
  function: <FunctionSquare className="size-3.5 text-violet-400" />, method: <FunctionSquare className="size-3.5 text-violet-300" />, class: <Box className="size-3.5 text-amber-400" />,
};

export function Explorer({ repoId }: { repoId: string }) {
  const tree = useTree(repoId);
  const git = useGitStatus(repoId);
  const activeTab = useIde((s) => s.tabs.find((t) => t.id === s.activeTabId));
  const openFile = useIde((s) => s.openFile);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const activePath = activeTab?.kind === "file" ? activeTab.path : undefined;
  const symbols = useFileSymbols(repoId, activePath);

  const root = useMemo(() => buildTree(tree.data ?? []), [tree.data]);
  const status = useMemo(() => new Map((git.data?.files ?? []).map((f) => [f.path, f])), [git.data]);
  const toggle = (p: string) => setOpen((o) => { const n = new Set(o); if (n.has(p)) n.delete(p); else n.add(p); return n; });
  const hits = useMemo(() => {
    if (!filter) return [];
    return (tree.data ?? []).map((f) => [f, fuzzy(filter, f)] as const).filter(([, s]) => s >= 0).sort((a, b) => b[1] - a[1]).slice(0, 80).map(([f]) => f);
  }, [filter, tree.data]);

  // Expand to the active file once so the tree reflects where you are.
  const expandTo = activePath ? activePath.split("/").slice(0, -1).map((_, i, a) => a.slice(0, i + 1).join("/")) : [];
  const effectiveOpen = useMemo(() => new Set([...open, ...(open.size === 0 ? expandTo : [])]), [open, expandTo.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="px-3 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Explorer</div>
      <div className="px-2 pb-2"><Input placeholder="Filter files…" value={filter} onChange={(e) => setFilter(e.target.value)} /></div>
      <ScrollArea className="min-h-0 flex-1">
        {tree.isLoading && <div className="px-3 py-2 text-muted-foreground">Loading files…</div>}
        {filter
          ? hits.map((f) => (
              <button key={f} onClick={() => openFile(f)} className="flex h-6 w-full items-center gap-1.5 px-3 text-left hover:bg-accent/60" title={f}>
                <FileIcon name={f} /><span className="truncate">{f}</span>
              </button>
            ))
          : root.children.map((n) => <Row key={n.path} node={n} depth={0} open={effectiveOpen} toggle={toggle} active={activePath} status={status} />)}
        {filter && hits.length === 0 && <div className="px-3 py-2 text-muted-foreground">No matching files</div>}
      </ScrollArea>
      <div className="flex max-h-[38%] min-h-[96px] flex-col border-t">
        <div className="flex items-center gap-1.5 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"><Braces className="size-3" /> Outline</div>
        <ScrollArea className="min-h-0 flex-1">
          {!activePath && <div className="px-3 pb-2 text-muted-foreground">Open a file to see its functions.</div>}
          {activePath && symbols.data?.length === 0 && <div className="px-3 pb-2 text-muted-foreground">No functions or classes found.</div>}
          {symbols.data?.map((s) => (
            <button key={`${s.qualname}:${s.start}`} onClick={() => openFile(s.file, s.start, s.end)} className="flex h-6 w-full items-center gap-1.5 px-3 text-left hover:bg-accent/60" title={`${s.qualname} · line ${s.start}`}>
              {KIND_ICON[s.kind] ?? <Braces className="size-3.5" />}
              <span className="truncate">{s.qualname}</span>
              <span className="ml-auto text-[10px] text-muted-foreground">{s.start}</span>
            </button>
          ))}
        </ScrollArea>
      </div>
    </div>
  );
}
