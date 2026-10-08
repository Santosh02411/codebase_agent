"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Braces, FileText, Play, Search, Terminal } from "lucide-react";
import { useFileSymbols, useRepoSymbols, useReindex, useTree } from "@/hooks/queries";
import { useAgentRun } from "@/hooks/useAgentRun";
import { useIde, type PaletteMode } from "@/store/ide";
import { api } from "@/lib/api";
import { cn, fuzzy } from "@/lib/utils";
import { toast } from "sonner";

interface Item { id: string; label: string; detail?: string; icon: React.ReactNode; run: () => void }

/** Ctrl+P files · Ctrl+Shift+O functions in this file · Ctrl+T functions in the repository · Ctrl+Shift+P commands. */
export function CommandPalette({ repoId }: { repoId: string }) {
  const mode = useIde((s) => s.palette);
  const setPalette = useIde((s) => s.setPalette);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const activePath = useIde((s) => { const t = s.tabs.find((x) => x.id === s.activeTabId); return t?.kind === "file" ? t.path : undefined; });
  const tree = useTree(repoId);
  const fileSyms = useFileSymbols(repoId, mode === "symbols" ? activePath : undefined);
  const repoSyms = useRepoSymbols(mode === "workspace" ? repoId : null, mode === "workspace" ? q : "");
  const reindex = useReindex();
  const { run } = useAgentRun();

  useEffect(() => { setQ(""); setSel(0); if (mode) setTimeout(() => input.current?.focus(), 0); }, [mode]);
  const close = () => setPalette(null);

  const items: Item[] = useMemo(() => {
    const st = useIde.getState();
    if (mode === "files") {
      return (tree.data ?? []).map((f) => ({ f, s: fuzzy(q, f) })).filter((x) => x.s >= 0).sort((a, b) => b.s - a.s).slice(0, 60)
        .map(({ f }) => ({ id: f, label: f.split("/").pop()!, detail: f, icon: <FileText className="size-3.5 text-sky-400" />, run: () => st.openFile(f) }));
    }
    if (mode === "symbols") {
      return (fileSyms.data ?? []).map((s) => ({ s, sc: fuzzy(q, s.qualname) })).filter((x) => x.sc >= 0).sort((a, b) => (q ? b.sc - a.sc : a.s.start - b.s.start))
        .map(({ s }) => ({ id: `${s.qualname}:${s.start}`, label: s.qualname, detail: `${s.kind} · line ${s.start}`, icon: <Braces className="size-3.5 text-violet-400" />, run: () => st.openFile(s.file, s.start, s.end) }));
    }
    if (mode === "workspace") {
      return (repoSyms.data ?? []).slice(0, 80).map((s) => ({ id: `${s.file}:${s.qualname}:${s.start}`, label: s.qualname, detail: `${s.file}:${s.start}${s.route ? ` · ${s.route}` : ""}`, icon: <Braces className="size-3.5 text-violet-400" />, run: () => st.openFile(s.file, s.start, s.end) }));
    }
    if (mode === "commands") {
      const cmds: Item[] = [
        { id: "tests", label: "Run tests", icon: <Play className="size-3.5" />, run: () => { st.setBottom("tests"); api.runTests(repoId).then((t) => st.addTest("Command palette", t)).catch((e: Error) => toast.error(e.message)); } },
        { id: "arch", label: "AI: Explain architecture", icon: <Search className="size-3.5" />, run: () => void run("architecture", "Explain the architecture") },
        { id: "review", label: "AI: Review whole project", icon: <Search className="size-3.5" />, run: () => void run("review", "Review the whole project") },
        { id: "reindex", label: "Re-index repository", icon: <Search className="size-3.5" />, run: () => reindex.mutate(repoId) },
        { id: "term", label: "Show terminal", icon: <Terminal className="size-3.5" />, run: () => st.setBottom("terminal") },
        { id: "act", label: "Show agent activity", icon: <Terminal className="size-3.5" />, run: () => st.setBottom("activity") },
        { id: "chat", label: "Toggle AI chat", icon: <Terminal className="size-3.5" />, run: () => st.toggleChat() },
        { id: "sym", label: "Go to function in file…", icon: <Braces className="size-3.5" />, run: () => setTimeout(() => st.setPalette("symbols"), 0) },
        { id: "wsym", label: "Go to function in repository…", icon: <Braces className="size-3.5" />, run: () => setTimeout(() => st.setPalette("workspace"), 0) },
      ];
      return cmds.filter((c) => fuzzy(q, c.label) >= 0);
    }
    return [];
  }, [mode, q, tree.data, fileSyms.data, repoSyms.data, repoId, reindex, run]);

  useEffect(() => setSel(0), [q, mode]);
  if (!mode) return null;
  const titles: Record<PaletteMode, string> = { files: "Go to file", symbols: `Go to function in ${activePath ?? "file"}`, workspace: "Go to function in repository", commands: "Commands" };
  const choose = (i: Item | undefined) => { if (!i) return; close(); i.run(); };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[12vh]" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="w-[600px] max-w-[94vw] overflow-hidden rounded-xl border bg-panel shadow-2xl">
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder={titles[mode]} spellCheck={false}
          className="w-full border-b bg-transparent px-4 py-3 text-sm outline-none"
          onKeyDown={(e) => {
            if (e.key === "Escape") close();
            else if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
            else if (e.key === "Enter") { e.preventDefault(); choose(items[sel]); }
          }} />
        <div className="max-h-[50vh] overflow-y-auto py-1">
          {mode === "symbols" && !activePath && <div className="px-4 py-3 text-muted-foreground">Open a file first.</div>}
          {items.length === 0 && (mode !== "symbols" || activePath) && <div className="px-4 py-3 text-muted-foreground">No results.</div>}
          {items.map((it, i) => (
            <button key={it.id} onMouseEnter={() => setSel(i)} onClick={() => choose(it)} className={cn("flex w-full items-center gap-2 px-4 py-1.5 text-left", i === sel && "bg-accent")}>
              {it.icon}<span className="truncate">{it.label}</span>{it.detail && <span className="ml-1 truncate text-muted-foreground">{it.detail}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
