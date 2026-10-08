"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Editor, { type Monaco, type OnMount } from "@monaco-editor/react";
import type { editor as MonacoNS } from "monaco-editor";
import { toast } from "sonner";
import { useFile, useSaveFile } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { languageOf } from "@/lib/languages";
import { api } from "@/lib/api";

type Ed = MonacoNS.IStandaloneCodeEditor;

export function MonacoEditor({ repoId, path }: { repoId: string; path: string }) {
  const file = useFile(repoId, path);
  const save = useSaveFile(repoId);
  const buffer = useIde((s) => s.buffers[path]);
  const reveal = useIde((s) => s.reveal);
  const [ready, setReady] = useState(false);
  const edRef = useRef<Ed | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  const decoRef = useRef<MonacoNS.IEditorDecorationsCollection | null>(null);
  const pathRef = useRef(path);
  pathRef.current = path;
  const textRef = useRef("");
  const serverText = file.data?.text;

  // Latest server text for the "is it dirty?" check in handlers created once at mount.
  textRef.current = serverText ?? "";

  const doSave = useCallback(async () => {
    const ed = edRef.current;
    if (!ed) return;
    const text = ed.getValue();
    const p = pathRef.current;
    if (text === textRef.current) return;
    await save.mutateAsync({ path: p, text });
    useIde.getState().setBuffer(p, null);
    toast.success(`Saved ${p} to the project copy`);
  }, [save]);
  const saveRef = useRef(doSave);
  saveRef.current = doSave;

  // Server copy changed underneath us (applied change, discard): refresh the model unless there are unsaved edits.
  useEffect(() => {
    const ed = edRef.current;
    if (!ed || serverText === undefined || buffer !== undefined) return;
    if (ed.getValue() !== serverText) ed.setValue(serverText);
  }, [serverText, buffer, ready, path]);

  // Jump to function / search hit / citation, with a brief highlight.
  useEffect(() => {
    const ed = edRef.current, monaco = monacoRef.current;
    if (!ed || !monaco || !reveal || reveal.path !== path || serverText === undefined) return;
    const apply = () => {
      const last = ed.getModel()?.getLineCount() ?? reveal.line;
      const a = Math.min(reveal.line, last), b = Math.min(Math.max(reveal.endLine, a), last);
      ed.revealLinesInCenter(a, b);
      ed.setSelection(new monaco.Selection(a, 1, a, 1));
      decoRef.current?.clear();
      decoRef.current = ed.createDecorationsCollection([
        { range: new monaco.Range(a, 1, b, 1), options: { isWholeLine: true, className: "reveal-line", linesDecorationsClassName: "reveal-glyph" } },
      ]);
      window.setTimeout(() => decoRef.current?.clear(), 2800);
      ed.focus();
    };
    const t = window.setTimeout(apply, 60); // let the model for a freshly opened tab attach first
    return () => window.clearTimeout(t);
  }, [reveal, path, serverText, ready]);

  const symbolIndex = useRef<Map<string, { file: string; start: number }>>(new Map());

  const goToDefinition = useCallback(async (word: string) => {
    if (!word) return;
    const cached = symbolIndex.current.get(word);
    const hit = cached ?? (await api.symbols(repoId, { q: word })).find((s) => s.name === word);
    if (!hit) { toast.message(`No definition found for “${word}” in this repository`); return; }
    symbolIndex.current.set(word, { file: hit.file, start: hit.start });
    useIde.getState().openFile(hit.file, hit.start);
  }, [repoId]);
  const gotoRef = useRef(goToDefinition);
  gotoRef.current = goToDefinition;

  const onMount: OnMount = useCallback((ed, monaco) => {
    edRef.current = ed;
    monacoRef.current = monaco;
    setReady(true);
    const st = () => useIde.getState();

    ed.onDidChangeCursorPosition((e) => st().setCursor(e.position.lineNumber, e.position.column));
    ed.onDidChangeCursorSelection(() => {
      const sel = ed.getSelection(), model = ed.getModel();
      if (!sel || !model || sel.isEmpty()) { if (st().selection?.file === pathRef.current) st().setSelection(null); return; }
      const text = model.getValueInRange(sel);
      if (text.trim().length < 2) { st().setSelection(null); return; }
      st().setSelection({ file: pathRef.current, startLine: sel.startLineNumber, endLine: sel.endLineNumber, text: text.slice(0, 6000) });
    });
    ed.onDidChangeModelContent(() => {
      const p = pathRef.current, v = ed.getValue();
      st().setBuffer(p, v === textRef.current ? null : v);
    });

    ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => void saveRef.current());
    ed.addAction({
      id: "agent.ask", label: "Ask AI about selection", keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyL],
      contextMenuGroupId: "9_agent", contextMenuOrder: 1,
      run: () => {
        const s = st().selection;
        if (s) st().setAttachment(s);
        st().setChatOpen(true);
        window.dispatchEvent(new Event("agent:focus-chat"));
      },
    });
    ed.addAction({
      id: "agent.definition", label: "Go to Definition (repository)", keybindings: [monaco.KeyCode.F12],
      contextMenuGroupId: "navigation", contextMenuOrder: 1.5,
      run: (e) => { const pos = e.getPosition(), w = pos && e.getModel()?.getWordAtPosition(pos); if (w) void gotoRef.current(w.word); },
    });
    ed.onMouseDown((e) => {
      if (!(e.event.ctrlKey || e.event.metaKey) || !e.target.position) return;
      const w = ed.getModel()?.getWordAtPosition(e.target.position);
      if (w) void gotoRef.current(w.word);
    });
  }, []);

  const language = useMemo(() => languageOf(path), [path]);

  return (
    <div className="relative h-full">
    {file.isLoading && <div className="absolute inset-0 z-10 bg-background/80 p-4 text-muted-foreground">Opening {path}…</div>}
    {file.error && <div className="absolute inset-0 z-10 bg-background p-4 text-destructive">{(file.error as Error).message}</div>}
    <Editor
      keepCurrentModel
      height="100%"
      path={`repo:${repoId}/${path}`}
      language={language}
      defaultValue={buffer ?? serverText ?? ""}
      theme="vs-dark"
      onMount={onMount}
      options={{
        fontSize: 13, fontFamily: "JetBrains Mono, ui-monospace, Menlo, Consolas, monospace", minimap: { enabled: true, scale: 1 },
        scrollBeyondLastLine: false, smoothScrolling: true, renderWhitespace: "selection", bracketPairColorization: { enabled: true },
        stickyScroll: { enabled: true }, automaticLayout: true, padding: { top: 8 }, tabSize: 4, wordWrap: "off",
      }}
    />
    </div>
  );
}
