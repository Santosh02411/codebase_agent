"use client";
import { Fragment, useMemo } from "react";
import { ChevronRight, FileSearch, GitCompare, MessageSquarePlus, Sparkles, TestTube2, Wand2, X, FileDiff, Keyboard } from "lucide-react";
import { useFileSymbols } from "@/hooks/queries";
import { useAgentRun } from "@/hooks/useAgentRun";
import { useIde, type Tab } from "@/store/ide";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { FileIcon } from "./Explorer";
import { GitDiffTab, ReviewTab } from "./DiffViews";
import { MonacoEditor } from "./MonacoEditor";

function TabButton({ tab, active }: { tab: Tab; active: boolean }) {
  const { setActiveTab, closeTab } = useIde.getState();
  const dirty = useIde((s) => !!tab.path && tab.kind === "file" && s.buffers[tab.path] !== undefined);
  const proposal = useIde((s) => (tab.proposalId ? s.proposals[tab.proposalId] : undefined));
  return (
    <div
      role="tab"
      onClick={() => setActiveTab(tab.id)}
      onAuxClick={(e) => e.button === 1 && closeTab(tab.id)}
      className={cn("group flex h-9 shrink-0 cursor-pointer items-center gap-1.5 border-r px-3", active ? "bg-background text-foreground" : "bg-panel text-muted-foreground hover:bg-accent/40")}
      title={tab.path ?? tab.title}
    >
      {tab.kind === "file" && tab.path && <FileIcon name={tab.path} />}
      {tab.kind === "review" && <FileDiff className="size-3.5 text-primary" />}
      {tab.kind === "diff" && <GitCompare className="size-3.5 text-amber-400" />}
      <span className="max-w-48 truncate">{tab.title}</span>
      {proposal?.applied && <span className="text-[10px] text-success">applied</span>}
      <button
        onClick={(e) => { e.stopPropagation(); if (dirty && !confirm(`${tab.title} has unsaved changes. Close anyway?`)) return; closeTab(tab.id); }}
        className="ml-1 rounded p-0.5 opacity-60 hover:bg-accent hover:opacity-100"
        aria-label="Close tab"
      >
        {dirty ? <span className="block size-2 rounded-full bg-foreground/80 group-hover:hidden" /> : null}
        <X className={cn("size-3.5", dirty && "hidden group-hover:block")} />
      </button>
    </div>
  );
}

function Breadcrumbs({ repoId, path }: { repoId: string; path: string }) {
  const line = useIde((s) => s.cursor.line);
  const syms = useFileSymbols(repoId, path);
  const current = useMemo(() => {
    const inside = (syms.data ?? []).filter((s) => s.start <= line && line <= s.end);
    return inside.sort((a, b) => b.start - a.start)[0];
  }, [syms.data, line]);
  return (
    <div className="flex h-6 items-center gap-1 overflow-hidden border-b bg-background px-3 text-[11px] text-muted-foreground">
      {path.split("/").map((seg, i, a) => (
        <span key={i} className="flex items-center gap-1">{seg}{i < a.length - 1 && <ChevronRight className="size-3" />}</span>
      ))}
      {current && <><ChevronRight className="size-3" /><span className="text-foreground">{current.qualname}</span></>}
    </div>
  );
}

/** Floating actions for selected code: ask a question, explain, write tests, or request a change. */
function SelectionBar() {
  const selection = useIde((s) => s.selection);
  const { run } = useAgentRun();
  if (!selection) return null;
  const quick = (mode: "chat" | "change" | "tests", text: string) => {
    const st = useIde.getState();
    st.setAttachment(selection);
    st.setChatOpen(true);
    void run(mode, text, mode === "tests" ? { target: selection.file } : {});
  };
  return (
    <div className="absolute right-6 top-2 z-20 flex items-center gap-1 rounded-lg border bg-panel/95 p-1 shadow-lg backdrop-blur">
      <span className="px-2 text-[11px] text-muted-foreground">{selection.file.split("/").pop()}:{selection.startLine}{selection.endLine > selection.startLine ? `–${selection.endLine}` : ""}</span>
      <Button size="xs" variant="secondary" onClick={() => { const st = useIde.getState(); st.setAttachment(selection); st.setChatOpen(true); window.dispatchEvent(new Event("agent:focus-chat")); }}><MessageSquarePlus /> Ask AI</Button>
      <Button size="xs" variant="ghost" onClick={() => quick("chat", "Explain what this code does and point out anything risky.")}><Sparkles /> Explain</Button>
      <Button size="xs" variant="ghost" onClick={() => quick("tests", `Write tests for the selected code in ${selection.file}.`)}><TestTube2 /> Tests</Button>
      <Button size="xs" variant="ghost" onClick={() => { const st = useIde.getState(); st.setAttachment(selection); st.setMode("change"); st.setChatOpen(true); window.dispatchEvent(new Event("agent:focus-chat")); }}><Wand2 /> Change…</Button>
    </div>
  );
}

function Welcome() {
  const setPalette = useIde((s) => s.setPalette);
  const rows: [string, string][] = [["Ctrl+P", "Open file"], ["Ctrl+Shift+O", "Go to function in file"], ["Ctrl+T", "Go to function in repository"], ["Ctrl+Shift+P", "Commands"], ["Ctrl+L", "Ask AI about selection"], ["Ctrl+S", "Save to project copy"], ["F12 / Ctrl+click", "Go to definition"]];
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 text-muted-foreground">
      <FileSearch className="size-10 opacity-40" />
      <div className="text-center"><div className="text-base font-medium text-foreground">Open a file to start</div><div className="mt-1">Pick one in the Explorer, or press Ctrl+P.</div></div>
      <div className="grid grid-cols-[auto_auto] gap-x-6 gap-y-1.5 text-xs">
        {rows.map(([k, v]) => (<Fragment key={k}><kbd className="rounded border bg-panel px-1.5 py-0.5 font-mono text-[11px] text-foreground">{k}</kbd><span>{v}</span></Fragment>))}
      </div>
      <Button size="sm" variant="outline" onClick={() => setPalette("files")}><Keyboard /> Quick open</Button>
    </div>
  );
}

export function EditorArea({ repoId }: { repoId: string }) {
  const tabs = useIde((s) => s.tabs);
  const activeId = useIde((s) => s.activeTabId);
  const active = tabs.find((t) => t.id === activeId);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div role="tablist" className="flex shrink-0 overflow-x-auto border-b bg-panel">{tabs.map((t) => <TabButton key={t.id} tab={t} active={t.id === activeId} />)}</div>
      {active?.kind === "file" && active.path && <Breadcrumbs repoId={repoId} path={active.path} />}
      <div className="relative min-h-0 flex-1">
        {!active && <Welcome />}
        {active?.kind === "file" && active.path && <><MonacoEditor repoId={repoId} path={active.path} /><SelectionBar /></>}
        {active?.kind === "review" && active.proposalId && <ReviewTab key={active.proposalId} repoId={repoId} proposalId={active.proposalId} />}
        {active?.kind === "diff" && active.path && <GitDiffTab key={active.path} repoId={repoId} path={active.path} />}
      </div>
    </div>
  );
}
