"use client";
import { useEffect } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { Bot, ChevronUp, FolderTree, GitBranch, GitCommitHorizontal, Loader2, PanelBottom, PanelRight, Plus, RefreshCw, Search, Sparkles, Terminal } from "lucide-react";
import { useGitStatus, useHealth, useRepos, useReindex } from "@/hooks/queries";
import { useIde, type SidebarView } from "@/store/ide";
import { Button } from "@/components/ui/button";
import { Tip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { AddRepoDialog } from "./AddRepoDialog";
import { BottomPanel } from "./BottomPanel";
import { ChatPanel } from "./ChatPanel";
import { CommandPalette } from "./CommandPalette";
import { EditorArea } from "./EditorArea";
import { Explorer } from "./Explorer";
import { GitPanel } from "./GitPanel";
import { SearchPanel } from "./SearchPanel";
import { useState } from "react";

function Handle({ vertical = false }: { vertical?: boolean }) {
  return <PanelResizeHandle className={cn("bg-border transition-colors hover:bg-primary/60 data-[resize-handle-state=drag]:bg-primary", vertical ? "h-px" : "w-px")} />;
}

function ActivityBar() {
  const sidebar = useIde((s) => s.sidebar);
  const setSidebar = useIde((s) => s.setSidebar);
  const repoId = useIde((s) => s.repoId);
  const git = useGitStatus(repoId);
  const n = git.data?.files.length ?? 0;
  const Btn = ({ id, icon, label, badge }: { id: SidebarView; icon: React.ReactNode; label: string; badge?: number }) => (
    <Tip label={label} side="right">
      <button onClick={() => setSidebar(id)} className={cn("relative flex size-10 items-center justify-center text-muted-foreground hover:text-foreground [&_svg]:size-5", sidebar === id && "border-l-2 border-primary text-foreground")}>
        {icon}{!!badge && <span className="absolute right-1 top-1 min-w-4 rounded-full bg-primary px-1 text-center text-[9px] font-bold leading-4 text-primary-foreground">{badge}</span>}
      </button>
    </Tip>
  );
  return (
    <div className="flex w-10 shrink-0 flex-col items-center border-r bg-panel">
      <Btn id="explorer" icon={<FolderTree />} label="Explorer" />
      <Btn id="search" icon={<Search />} label="Search" />
      <Btn id="git" icon={<GitBranch />} label="Git changes" badge={n} />
    </div>
  );
}

function TopBar({ onAdd }: { onAdd: () => void }) {
  const repos = useRepos();
  const repoId = useIde((s) => s.repoId);
  const setRepoId = useIde((s) => s.setRepoId);
  const { setPalette, toggleBottom, toggleChat, bottomOpen, chatOpen } = useIde();
  const reindex = useReindex();
  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b bg-panel px-3">
      <div className="flex items-center gap-1.5 font-semibold"><Sparkles className="size-4 text-primary" />Codebase Agent</div>
      <select value={repoId ?? ""} onChange={(e) => setRepoId(e.target.value || null)} className="ml-3 h-7 max-w-64 rounded-md border border-input bg-background px-2 text-xs">
        {!repos.data?.length && <option value="">No repositories</option>}
        {repos.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
      </select>
      <Button size="sm" variant="outline" onClick={onAdd}><Plus /> Add</Button>
      {repoId && <Tip label="Re-index after external changes"><Button size="icon" variant="ghost" disabled={reindex.isPending} onClick={() => reindex.mutate(repoId)}><RefreshCw className={cn(reindex.isPending && "animate-spin")} /></Button></Tip>}
      <button onClick={() => setPalette("files")} className="mx-auto hidden h-7 w-80 items-center gap-2 rounded-md border bg-background px-2.5 text-muted-foreground hover:border-primary md:flex"><Search className="size-3.5" /><span>Search files, functions, commands</span><kbd className="ml-auto rounded border px-1 font-mono text-[10px]">Ctrl P</kbd></button>
      <div className="ml-auto flex gap-0.5 md:ml-0">
        <Tip label="Toggle bottom panel"><Button size="icon" variant="ghost" className={cn(bottomOpen && "bg-accent")} onClick={toggleBottom}><PanelBottom /></Button></Tip>
        <Tip label="Toggle AI chat"><Button size="icon" variant="ghost" className={cn(chatOpen && "bg-accent")} onClick={toggleChat}><PanelRight /></Button></Tip>
      </div>
    </div>
  );
}

function StatusBar() {
  const repoId = useIde((s) => s.repoId);
  const repos = useRepos();
  const health = useHealth();
  const git = useGitStatus(repoId);
  const cursor = useIde((s) => s.cursor);
  const running = useIde((s) => s.runs.some((r) => r.state === "running"));
  const selection = useIde((s) => s.selection);
  const dirty = useIde((s) => Object.keys(s.buffers).length);
  const setBottom = useIde((s) => s.setBottom);
  const repo = repos.data?.find((r) => r.id === repoId);
  return (
    <div className="flex h-6 shrink-0 items-center gap-4 border-t bg-primary/90 px-3 text-[11px] text-primary-foreground">
      <span className="flex items-center gap-1"><GitBranch className="size-3" />{git.data?.branch || "—"}</span>
      {!!git.data?.files.length && <span className="flex items-center gap-1"><GitCommitHorizontal className="size-3" />{git.data.files.length} changed</span>}
      {dirty > 0 && <span>{dirty} unsaved</span>}
      {repo && <span>{repo.files} files · {repo.chunks} chunks · {repo.embedder}</span>}
      <button className="flex items-center gap-1 hover:underline" onClick={() => setBottom("activity")}>{running ? <><Loader2 className="size-3 animate-spin" />Agent working…</> : <><Bot className="size-3" />Agent idle</>}</button>
      <span className="ml-auto flex items-center gap-4">
        {selection && <span>{selection.endLine - selection.startLine + 1} lines selected</span>}
        <span>Ln {cursor.line}, Col {cursor.col}</span>
        <span>{health.data ? `LLM: ${health.data.llm_provider}${health.data.llm_model ? ` / ${health.data.llm_model}` : ""}` : health.isError ? "API offline" : "…"}</span>
      </span>
    </div>
  );
}

function Landing({ onAdd }: { onAdd: () => void }) {
  const health = useHealth();
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <Sparkles className="size-10 text-primary" />
      <div className="text-xl font-semibold">AI development environment</div>
      {health.isError ? (
        <div className="max-w-md rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-left">
          <div className="font-medium text-destructive">Can’t reach the backend</div>
          <div className="mt-1 text-muted-foreground">{(health.error as Error).message}</div>
          <pre className="mt-2 rounded bg-background p-2 font-mono text-[11px]">uvicorn app.main:app --reload</pre>
        </div>
      ) : (
        <div className="max-w-md text-muted-foreground">Add a GitHub repository or upload a ZIP. The agent indexes it, then you can explore, search, ask, debug and review changes with full visibility.</div>
      )}
      <Button onClick={onAdd}><Plus /> Add a repository</Button>
    </div>
  );
}

export function Workbench() {
  const repos = useRepos();
  const repoId = useIde((s) => s.repoId);
  const setRepoId = useIde((s) => s.setRepoId);
  const sidebar = useIde((s) => s.sidebar);
  const bottomOpen = useIde((s) => s.bottomOpen);
  const chatOpen = useIde((s) => s.chatOpen);
  const [adding, setAdding] = useState(false);

  // Keep the selected repository valid (first one by default; clear if it was removed on the server).
  useEffect(() => {
    if (!repos.data) return;
    if (repoId && !repos.data.some((r) => r.id === repoId)) setRepoId(repos.data[0]?.id ?? null);
    else if (!repoId && repos.data.length) setRepoId(repos.data[0].id);
  }, [repos.data, repoId, setRepoId]);

  // Global shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      const k = e.key.toLowerCase();
      const st = useIde.getState();
      if (k === "p" && !e.shiftKey) { e.preventDefault(); st.setPalette("files"); }
      else if (k === "p" && e.shiftKey) { e.preventDefault(); st.setPalette("commands"); }
      else if (k === "o" && e.shiftKey) { e.preventDefault(); st.setPalette("symbols"); }
      else if (k === "t" && !e.shiftKey) { e.preventDefault(); st.setPalette("workspace"); }
      else if (k === "f" && e.shiftKey) { e.preventDefault(); st.setSidebar("search"); }
      else if (k === "j") { e.preventDefault(); st.toggleBottom(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-screen flex-col">
      <TopBar onAdd={() => setAdding(true)} />
      {!repoId ? (
        <div className="min-h-0 flex-1"><Landing onAdd={() => setAdding(true)} /></div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <ActivityBar />
          <PanelGroup direction="horizontal" autoSaveId="ide-h" className="min-w-0 flex-1">
            <Panel id="side" order={1} defaultSize={20} minSize={13} maxSize={40} className="bg-panel">
              {sidebar === "explorer" && <Explorer repoId={repoId} />}
              {sidebar === "search" && <SearchPanel repoId={repoId} />}
              {sidebar === "git" && <GitPanel repoId={repoId} />}
            </Panel>
            <Handle />
            <Panel id="main" order={2} minSize={30} className="relative">
              <PanelGroup direction="vertical" autoSaveId="ide-v">
                <Panel id="editor" order={1} minSize={20}><EditorArea repoId={repoId} /></Panel>
                {bottomOpen && (<><Handle vertical /><Panel id="bottom" order={2} defaultSize={32} minSize={12} maxSize={75}><BottomPanel repoId={repoId} /></Panel></>)}
              </PanelGroup>
              {!bottomOpen && <BottomToggle />}
            </Panel>
            {chatOpen && (<><Handle /><Panel id="chat" order={3} defaultSize={28} minSize={20} maxSize={50}><ChatPanel /></Panel></>)}
          </PanelGroup>
        </div>
      )}
      <StatusBar />
      {repoId && <CommandPalette repoId={repoId} />}
      {adding && <AddRepoDialog onClose={() => setAdding(false)} />}
    </div>
  );
}

function BottomToggle() {
  const toggle = useIde((s) => s.toggleBottom);
  return <button onClick={toggle} className="absolute bottom-2 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border bg-panel px-3 py-1 text-[11px] text-muted-foreground shadow hover:text-foreground"><Terminal className="size-3" />Activity · Terminal · Tests<ChevronUp className="size-3" /></button>;
}
