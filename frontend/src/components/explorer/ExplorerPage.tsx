"use client";
import { Suspense } from "react";
import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { DiffEditor } from "@monaco-editor/react";
import dynamic from "next/dynamic";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { FolderTree, GitCompare, MessageSquarePlus, PanelLeft, PanelRight, FileCode2 } from "lucide-react";
import { useFileSymbols, useGitStatus, useGitVersions, useStats } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { useMedia } from "@/hooks/useMedia";
import { useAskAbout } from "@/hooks/useOpen";
import { languageOf } from "@/lib/languages";
import { useMonacoTheme } from "@/lib/monacoTheme";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";
import { FileLink } from "@/components/common/bits";
import { FileTree } from "./FileTree";
import { Inspector } from "./Inspector";

const MonacoEditor = dynamic(() => import("@/components/ide/MonacoEditor").then((m) => m.MonacoEditor), { ssr: false, loading: () => <div className="p-4"><Skeleton className="h-64" /></div> });
const HANDLE = "group relative w-px bg-border transition-colors hover:bg-primary/50 data-[resize-handle-state=drag]:bg-primary after:absolute after:inset-y-0 after:-left-1 after:-right-1";

function Welcome({ repoId, onOpen }: { repoId: string; onOpen: (p: string, l?: number) => void }) {
  const stats = useStats(repoId);
  const entry = [...new Set((stats.data?.apis.items ?? []).map((a) => a.file))].slice(0, 5);
  return (
    <EmptyState className="h-full" art={<div className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary"><FolderTree className="size-6" /></div>} title="Open a file to start exploring"
      description={<>Pick a file in the tree, or press <kbd className="rounded border bg-secondary px-1 font-mono text-[10px]">Ctrl K</kbd> to jump to any file or symbol.</>}
      action={entry.length > 0 ? <div className="space-y-1 text-left"><div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Files with API routes</div>{entry.map((f) => <div key={f}><button onClick={() => onOpen(f)} className="font-mono text-xs text-primary hover:underline">{f}</button></div>)}</div> : undefined} />
  );
}

function ChangesView({ repoId, path }: { repoId: string; path: string }) {
  const v = useGitVersions(repoId, path);
  const theme = useMonacoTheme();
  if (v.isLoading) return <div className="p-4"><Skeleton className="h-64" /></div>;
  return <DiffEditor height="100%" theme={theme} language={languageOf(path)} original={v.data?.original ?? ""} modified={v.data?.modified ?? ""} options={{ readOnly: true, renderSideBySide: true, automaticLayout: true, fontSize: 13, minimap: { enabled: false }, scrollBeyondLastLine: false }} />;
}

function ExplorerPageInner({ repoId }: { repoId: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const file = params.get("file") ?? undefined;
  const line = Number(params.get("line")) || undefined;
  const end = Number(params.get("end")) || undefined;
  const wide = useMedia("(min-width: 1024px)");
  const [treeOpen, setTreeOpen] = useState(false);
  const [inspOpen, setInspOpen] = useState(false);
  const [diff, setDiff] = useState(false);
  const git = useGitStatus(repoId);
  const symbols = useFileSymbols(repoId, file);
  const cursor = useIde((s) => s.cursor);
  const dirty = useIde((s) => (file ? s.buffers[file] !== undefined : false));
  const selection = useIde((s) => s.selection);
  const ask = useAskAbout();
  const status = file ? git.data?.files.find((f) => f.path === file)?.status : undefined;
  const here = useMemo(() => (symbols.data ?? []).filter((s) => cursor.line >= s.start && cursor.line <= s.end).sort((a, b) => (a.end - a.start) - (b.end - b.start))[0] ?? null, [symbols.data, cursor.line]);

  useEffect(() => { if (file && line) useIde.setState({ reveal: { path: file, line, endLine: end ?? line, nonce: Date.now() } }); }, [file, line, end]);
  useEffect(() => { setDiff(false); }, [file]);
  // Ctrl+L / "Ask AI about selection" in the editor: the selection is already attached, so go to the chat
  useEffect(() => { const f = () => router.push("/chat"); window.addEventListener("agent:ask-selection", f); return () => window.removeEventListener("agent:ask-selection", f); }, [router]);

  const open = (p: string, l?: number, e?: number) => {
    const q = new URLSearchParams({ file: p });
    if (l) q.set("line", String(l)); if (e && e !== l) q.set("end", String(e));
    router.push(`/explorer?${q.toString()}`);
    setTreeOpen(false);
  };

  const editor = (
    <div className="flex h-full min-w-0 flex-col">
      {file && (
        <div className="flex h-10 shrink-0 items-center gap-2 border-b px-3 text-[13px]">
          {!wide && <Button size="icon-sm" variant="ghost" onClick={() => setTreeOpen(true)} aria-label="Show files"><PanelLeft /></Button>}
          <FileCode2 className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 truncate font-medium" title={file}>{file}</span>
          {dirty && <Badge variant="warning">unsaved</Badge>}
          {status && <Badge variant="secondary" className="capitalize">{status}</Badge>}
          {here && <span className="hidden truncate text-muted-foreground md:inline">› {here.qualname}</span>}
          <div className="ml-auto flex items-center gap-1">
            {status && <Button size="xs" variant={diff ? "secondary" : "ghost"} onClick={() => setDiff(!diff)}><GitCompare />{diff ? "Editor" : "Changes"}</Button>}
            <Button size="xs" variant="ghost" onClick={() => ask(selection && selection.file === file ? selection : { file, startLine: 1, endLine: 1, text: `(entire file ${file})` })}><MessageSquarePlus />Ask AI</Button>
            {!wide && <Button size="icon-sm" variant="ghost" onClick={() => setInspOpen(true)} aria-label="Show inspector"><PanelRight /></Button>}
          </div>
        </div>
      )}
      <div className="min-h-0 flex-1">
        {!file ? <Welcome repoId={repoId} onOpen={open} /> : diff ? <ChangesView repoId={repoId} path={file} /> : <MonacoEditor key={file} repoId={repoId} path={file} />}
      </div>
      {file && <div className="flex h-6 shrink-0 items-center gap-3 border-t px-3 text-[11px] text-muted-foreground"><span>Ln {cursor.line}, Col {cursor.col}</span><span>{languageOf(file)}</span><span className="ml-auto hidden sm:inline">Ctrl+S saves to the project copy · F12 go to definition · Ctrl+L ask AI</span></div>}
    </div>
  );

  if (!wide) {
    return (
      <div className="h-full">
        {editor}
        <Drawer open={treeOpen} onOpenChange={setTreeOpen} title="Files" width="max-w-sm"><FileTree repoId={repoId} selected={file} onOpen={(p) => open(p)} /></Drawer>
        <Drawer open={inspOpen} onOpenChange={setInspOpen} title="Inspector" width="max-w-md"><div className="h-full"><Inspector repoId={repoId} file={file} symbolAtCursor={here} onOpen={open} /></div></Drawer>
      </div>
    );
  }
  return (
    <PanelGroup direction="horizontal" autoSaveId="explorer-layout" className="h-full">
      <Panel defaultSize={20} minSize={14} maxSize={34} className="bg-panel"><div className="flex h-full flex-col"><div className="flex h-10 shrink-0 items-center border-b px-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Files</div><div className="min-h-0 flex-1"><FileTree repoId={repoId} selected={file} onOpen={(p) => open(p)} /></div></div></Panel>
      <PanelResizeHandle className={cn(HANDLE)} />
      <Panel defaultSize={54} minSize={30}>{editor}</Panel>
      <PanelResizeHandle className={cn(HANDLE)} />
      <Panel defaultSize={26} minSize={18} maxSize={40} className="bg-panel"><Inspector repoId={repoId} file={file} symbolAtCursor={here} onOpen={open} /></Panel>
    </PanelGroup>
  );
}

/** useSearchParams needs a Suspense boundary; it lives INSIDE the project check so the server HTML and the first client render agree. */
export function ExplorerPage({ repoId }: { repoId: string }) {
  return <Suspense fallback={null}><ExplorerPageInner repoId={repoId} /></Suspense>;
}
