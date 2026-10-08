"use client";
import { useEffect, useRef, useState } from "react";
import { Bot, Bug, FileSearch, FlaskConical, Hammer, Layers, MessageCircle, Paperclip, Send, Square, X } from "lucide-react";
import { useHealth } from "@/hooks/queries";
import { useAgentRun } from "@/hooks/useAgentRun";
import { useIde } from "@/store/ide";
import type { Mode } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageView } from "./MessageView";

type UiMode = "chat" | "debug" | "change" | "tests" | "review" | "architecture";
const MODES: { id: UiMode; label: string; icon: React.ReactNode; hint: string; placeholder: string; needsText: boolean }[] = [
  { id: "chat", label: "Ask", icon: <MessageCircle />, hint: "Answer questions using the codebase", placeholder: "Ask about this codebase… (Enter to send, Shift+Enter for a new line)", needsText: true },
  { id: "debug", label: "Debug", icon: <Bug />, hint: "Find the root cause and propose a fix", placeholder: "Paste an error or describe the bug…", needsText: true },
  { id: "change", label: "Change", icon: <Hammer />, hint: "Write or modify code across files", placeholder: "Describe the change you want…", needsText: true },
  { id: "tests", label: "Tests", icon: <FlaskConical />, hint: "Generate tests for a file", placeholder: "Optional: what should the tests focus on? (uses the open file)", needsText: false },
  { id: "review", label: "Review", icon: <FileSearch />, hint: "Review the open file or the whole project", placeholder: "Optional: what should the review focus on?", needsText: false },
  { id: "architecture", label: "Arch", icon: <Layers />, hint: "Explain how the project is structured", placeholder: "", needsText: false },
];
const IDEAS: Record<UiMode, string[]> = {
  chat: ["Where is authentication handled?", "How does a request flow through this app?", "Which functions have no tests?"],
  debug: ["500 error when creating a delivery", "Why does this raise a TypeError when a field is missing?"],
  change: ["Add input validation to the create endpoint", "Extract the duplicated logic into a helper"],
  tests: [], review: [], architecture: [],
};

export function ChatPanel() {
  const { run, stop } = useAgentRun();
  const messages = useIde((s) => s.messages);
  const mode = useIde((s) => s.mode) as UiMode;
  const { setMode, provider, setProvider, verify, setVerify, attachment, setAttachment } = useIde();
  const running = useIde((s) => s.runs.some((r) => r.state === "running"));
  const activePath = useIde((s) => { const t = s.tabs.find((x) => x.id === s.activeTabId); return t?.kind === "file" ? t.path : undefined; });
  const health = useHealth();
  const [text, setText] = useState("");
  const [fileOnly, setFileOnly] = useState(true);
  const area = useRef<HTMLTextAreaElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const cfg = MODES.find((m) => m.id === mode) ?? MODES[0];

  useEffect(() => { const f = () => area.current?.focus(); window.addEventListener("agent:focus-chat", f); return () => window.removeEventListener("agent:focus-chat", f); }, []);
  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [messages, running]);

  const canSend = !running && (cfg.needsText ? text.trim().length > 0 : true) && !(mode === "tests" && !activePath && !attachment);
  const submit = () => {
    if (!canSend) return;
    const t = text.trim();
    const target = mode === "tests" ? (attachment?.file ?? activePath) : mode === "review" && fileOnly ? (attachment?.file ?? activePath) : undefined;
    const apiMode: Mode = mode === "debug" && !verify ? "fix" : mode;
    setText("");
    void run(apiMode, t || (mode === "tests" ? `Write tests for ${target}` : mode === "review" ? (target ? `Review ${target}` : "Review the whole project") : "Explain the architecture"), { target });
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-panel">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Bot className="size-4 text-primary" /><span className="font-semibold">AI assistant</span>
        <select value={provider} onChange={(e) => setProvider(e.target.value)} className="ml-auto h-7 rounded-md border border-input bg-background px-1.5 text-[11px]" title="Model provider for this request">
          <option value="">{`Server default (${health.data?.llm_provider ?? "…"})`}</option>
          <option value="mock">mock (offline)</option><option value="gemini">gemini</option><option value="openai">openai</option>
        </select>
      </div>
      <div className="flex gap-0.5 border-b px-2 py-1.5">
        {MODES.map((m) => (
          <button key={m.id} title={m.hint} onClick={() => setMode(m.id)} className={cn("flex flex-1 flex-col items-center gap-0.5 rounded-md px-1 py-1 text-[10.5px] [&_svg]:size-3.5", mode === m.id ? "bg-primary/20 text-primary" : "text-muted-foreground hover:bg-accent")}>{m.icon}{m.label}</button>
        ))}
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-3 p-3">
          {messages.length === 0 && (
            <div className="space-y-3 pt-4 text-muted-foreground">
              <div className="text-center"><Bot className="mx-auto mb-2 size-8 opacity-40" /><div className="font-medium text-foreground">{cfg.label}</div><div>{cfg.hint}</div></div>
              {IDEAS[mode].map((i) => <button key={i} onClick={() => { setText(i); area.current?.focus(); }} className="block w-full rounded-md border px-3 py-2 text-left hover:bg-accent">{i}</button>)}
              <div className="text-center text-[11px]">Select code in the editor to ask about it — or press <kbd className="rounded border px-1">Ctrl+L</kbd>.</div>
            </div>
          )}
          {messages.map((m) => <MessageView key={m.id} m={m} />)}
          <div ref={bottom} />
        </div>
      </ScrollArea>
      <div className="space-y-2 border-t p-2.5">
        {attachment && (
          <div className="flex items-center gap-1.5 rounded-md border bg-background px-2 py-1 font-mono text-[11px]">
            <Paperclip className="size-3 shrink-0 text-primary" /><span className="truncate">{attachment.file}:{attachment.startLine}-{attachment.endLine}</span>
            <span className="text-muted-foreground">({attachment.text.split("\n").length} lines attached)</span>
            <button className="ml-auto rounded p-0.5 hover:bg-accent" onClick={() => setAttachment(null)} aria-label="Remove attachment"><X className="size-3" /></button>
          </div>
        )}
        {(mode === "tests" || mode === "review") && (
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            {mode === "tests" && <span>Target: <span className="font-mono text-foreground">{attachment?.file ?? activePath ?? "open a file first"}</span></span>}
            {mode === "review" && <label className="flex items-center gap-1.5"><input type="checkbox" checked={fileOnly} onChange={(e) => setFileOnly(e.target.checked)} /> Current file only{fileOnly && activePath ? <span className="font-mono text-foreground">({activePath})</span> : null}</label>}
          </div>
        )}
        {cfg.placeholder !== "" && (
          <Textarea ref={area} rows={3} value={text} placeholder={cfg.placeholder} disabled={running} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }} />
        )}
        <div className="flex items-center gap-2">
          {(mode === "debug" || mode === "change" || mode === "tests") && (
            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground" title="Run the test suite in a sandbox copy before and after the change">
              <input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} /> Verify with tests
            </label>
          )}
          <div className="ml-auto flex gap-1.5">
            {running
              ? <Button size="sm" variant="destructive" onClick={stop}><Square /> Stop</Button>
              : <Button size="sm" disabled={!canSend} onClick={submit}><Send /> {mode === "architecture" ? "Explain architecture" : mode === "review" ? "Run review" : mode === "tests" ? "Generate tests" : "Send"}</Button>}
          </div>
        </div>
      </div>
    </div>
  );
}
