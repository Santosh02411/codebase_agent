"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, BookOpen, Brain, CheckCircle2, ChevronDown, ChevronRight, CircleDot, Loader2, Play, Search, TerminalSquare, TestTube2, Wrench, XCircle, GitBranch, Activity } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { toRows, type Row } from "@/lib/activity";
import { fmtMs, parseLines } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { useFile } from "@/hooks/queries";
import { useIde, type BottomTab } from "@/store/ide";
import type { Finding, Source } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function useNow(active: boolean) {
  const [, tick] = useState(0);
  useEffect(() => { if (!active) return; const t = setInterval(() => tick((n) => n + 1), 500); return () => clearInterval(t); }, [active]);
}

// ---- Agent activity -------------------------------------------------------------------------------
function RowIcon({ r }: { r: Row }) {
  if (r.state === "running") return <Loader2 className="size-3.5 animate-spin text-primary" />;
  if (r.state === "error") return <XCircle className="size-3.5 text-destructive" />;
  if (r.kind === "llm") return <Brain className="size-3.5 text-violet-400" />;
  if (r.kind === "tool") return r.title.toLowerCase().includes("search") ? <Search className="size-3.5 text-sky-400" /> : <Wrench className="size-3.5 text-sky-400" />;
  if (r.kind === "node") return <GitBranch className="size-3.5 text-amber-400" />;
  if (r.kind === "result") return <CheckCircle2 className="size-3.5 text-success" />;
  return <CircleDot className="size-3.5 text-muted-foreground" />;
}

export function ActivityPanel() {
  const runs = useIde((s) => s.runs);
  const activeRunId = useIde((s) => s.activeRunId);
  const setActiveRun = useIde((s) => s.setActiveRun);
  const openFile = useIde((s) => s.openFile);
  const run = runs.find((r) => r.id === activeRunId) ?? runs[runs.length - 1];
  const rows = useMemo(() => (run ? toRows(run) : []), [run]);
  const end = useRef<HTMLDivElement>(null);
  useNow(run?.state === "running");
  useEffect(() => { if (run?.state === "running") end.current?.scrollIntoView({ block: "end" }); }, [rows.length, run?.state]);

  if (!run) return <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground"><Activity className="size-6 opacity-40" /><div>Nothing yet. Ask the assistant something and every step appears here, live.</div></div>;
  const elapsed = ((run.ended ?? Date.now()) - run.started) / 1000;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b px-3 py-1.5">
        <select value={run.id} onChange={(e) => setActiveRun(e.target.value)} className="h-6 max-w-[40%] truncate rounded border border-input bg-background px-1 text-[11px]">
          {runs.map((r, i) => <option key={r.id} value={r.id}>{`#${i + 1} · ${r.mode} · ${r.label}`}</option>)}
        </select>
        <Badge variant={run.state === "running" ? "default" : run.state === "done" ? "success" : run.state === "error" ? "destructive" : "secondary"}>{run.state}</Badge>
        <span className="text-muted-foreground">{elapsed.toFixed(1)} s</span>
        <span className="ml-auto text-muted-foreground">{rows.filter((r) => r.kind === "tool").length} tool calls · {rows.filter((r) => r.kind === "llm").length} model calls</span>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="py-1 font-mono text-[11.5px]">
          {rows.map((r) => (
            <div key={r.key}>
              <div className={cn("flex items-start gap-2 px-3 py-[3px] hover:bg-accent/40", r.kind === "node" && "mt-1 font-semibold")} style={{ paddingLeft: 12 + r.depth * 18 }}>
                <span className="w-12 shrink-0 text-right text-muted-foreground">+{r.t.toFixed(1)}s</span>
                <span className="mt-0.5"><RowIcon r={r} /></span>
                <div className="min-w-0 flex-1">
                  <span className={cn(r.kind === "error" && "text-destructive")}>{r.title}</span>
                  {r.detail && <span className="ml-2 break-words text-muted-foreground">{r.detail}</span>}
                  {r.hits && r.hits.length > 0 && (
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {r.hits.slice(0, 6).map((h, i) => { const [a, b] = parseLines(h.lines); return <button key={i} onClick={() => openFile(h.file, a, b)} className="rounded border px-1 text-[10.5px] text-sky-300 hover:bg-accent">{h.file.split("/").pop()}:{h.lines}</button>; })}
                    </div>
                  )}
                </div>
                {r.ms != null && <span className="shrink-0 text-muted-foreground">{fmtMs(r.ms)}</span>}
              </div>
            </div>
          ))}
          <div ref={end} />
        </div>
      </ScrollArea>
    </div>
  );
}

// ---- Terminal -------------------------------------------------------------------------------------
export function TerminalPanel({ repoId }: { repoId: string }) {
  const lines = useIde((s) => s.termLines);
  const history = useIde((s) => s.termHistory);
  const { pushTerm, pushHistory, clearTerm, addTest } = useIde.getState();
  const [cmd, setCmd] = useState("");
  const [busy, setBusy] = useState(false);
  const [hi, setHi] = useState(-1);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [lines.length, busy]);
  useEffect(() => { if (useIde.getState().termLines.length === 0) pushTerm([{ kind: "out", text: "Restricted terminal for this project copy. Type `help`. Try: git status · grep <text> · pytest -q" }]); }, [pushTerm]);

  const exec = async (c: string) => {
    if (!c.trim()) return;
    if (c.trim() === "clear") { clearTerm(); return; }
    pushHistory(c); pushTerm([{ kind: "cmd", text: c }]); setBusy(true);
    try {
      const r = await api.terminal(repoId, c);
      if (r.output) pushTerm([{ kind: r.exit_code === 0 ? "out" : "err", text: r.output.replace(/\n$/, "") }]);
      if (r.tests) { addTest(`Terminal · ${c}`, r.tests); }
      if (/^(git|pytest|tests)/.test(c)) useIde.getState().setBottom("terminal");
    } catch (e) { pushTerm([{ kind: "err", text: (e as Error).message }]); }
    finally { setBusy(false); setTimeout(() => input.current?.focus(), 0); }
  };

  return (
    <div className="flex h-full min-h-0 flex-col font-mono text-[12px]" onClick={() => input.current?.focus()}>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-0.5 p-3">
          {lines.map((l) => (
            <pre key={l.id} className={cn("whitespace-pre-wrap break-words", l.kind === "cmd" && "text-sky-300", l.kind === "err" && "text-red-300")}>{l.kind === "cmd" ? `$ ${l.text}` : l.text}</pre>
          ))}
          {busy && <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="size-3 animate-spin" /> running…</div>}
          <div ref={end} />
        </div>
      </ScrollArea>
      <div className="flex items-center gap-2 border-t px-3 py-1.5">
        <span className="text-emerald-400">$</span>
        <input ref={input} value={cmd} disabled={busy} spellCheck={false} autoComplete="off" placeholder="help"
          onChange={(e) => setCmd(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { const c = cmd; setCmd(""); setHi(-1); void exec(c); }
            else if (e.key === "ArrowUp") { e.preventDefault(); const i = Math.min(hi + 1, history.length - 1); if (history.length) { setHi(i); setCmd(history[history.length - 1 - i]); } }
            else if (e.key === "ArrowDown") { e.preventDefault(); const i = hi - 1; setHi(i); setCmd(i < 0 ? "" : history[history.length - 1 - i]); }
          }}
          className="flex-1 bg-transparent outline-none placeholder:text-muted-foreground/50" />
      </div>
    </div>
  );
}

// ---- Test results ---------------------------------------------------------------------------------
export function TestsPanel({ repoId }: { repoId: string }) {
  const entries = useIde((s) => s.testRuns);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const m = useMutation({
    mutationFn: () => api.runTests(repoId),
    onSuccess: (t) => { useIde.getState().addTest("Manual run", t); },
    onError: (e: Error) => toast.error(e.message),
  });
  const first = entries[0]?.id;
  const isOpen = (id: string) => open.has(id) || (id === first && !open.has(`-${id}`));
  const toggle = (id: string) => setOpen((o) => { const n = new Set(o); if (isOpen(id)) { n.delete(id); n.add(`-${id}`); } else { n.delete(`-${id}`); n.add(id); } return n; });
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b px-3 py-1.5">
        <Button size="sm" onClick={() => m.mutate()} disabled={m.isPending}>{m.isPending ? <Loader2 className="animate-spin" /> : <Play />} Run tests</Button>
        <span className="text-muted-foreground">Runs in a throwaway copy with secrets removed from the environment.</span>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {entries.length === 0 && <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground"><TestTube2 className="size-6 opacity-40" />No test runs yet.</div>}
        {entries.map((e) => (
          <div key={e.id} className="border-b">
            <button onClick={() => toggle(e.id)} className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-accent/40">
              {isOpen(e.id) ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              <Badge variant={e.run.passed ? "success" : e.run.status === "no_tests" ? "secondary" : "destructive"}>{e.run.status.replace("_", " ")}</Badge>
              <span className="truncate">{e.run.summary || "(no summary)"}</span>
              <span className="ml-auto shrink-0 text-muted-foreground">{e.origin} · {new Date(e.ts).toLocaleTimeString()}</span>
            </button>
            {isOpen(e.id) && <pre className="max-h-64 overflow-auto whitespace-pre-wrap bg-background px-4 py-2 font-mono text-[11px] text-muted-foreground">{e.run.output || "(no output)"}</pre>}
          </div>
        ))}
      </ScrollArea>
    </div>
  );
}

// ---- Source citations -----------------------------------------------------------------------------
function Peek({ repoId, s }: { repoId: string; s: Source }) {
  const f = useFile(repoId, s.file);
  const [a, b] = parseLines(s.lines);
  const lines = f.data?.text.split("\n").slice(a - 1, Math.min(b, a + 24)) ?? [];
  return <pre className="max-h-48 overflow-auto bg-background px-4 py-2 font-mono text-[11px]">{f.isLoading ? "Loading…" : lines.map((l, i) => `${String(a + i).padStart(4)}  ${l}`).join("\n")}</pre>;
}

export function SourcesPanel({ repoId }: { repoId: string }) {
  const messages = useIde((s) => s.messages);
  const runs = useIde((s) => s.runs);
  const openFile = useIde((s) => s.openFile);
  const [peek, setPeek] = useState<string | null>(null);
  const live = runs.find((r) => r.state === "running");
  const liveHits: Source[] = live ? live.events.flatMap((e) => (e.type === "tool" && e.phase === "end" && e.hits ? e.hits : [])) : [];
  const groups = useMemo(() => {
    const out: { id: string; title: string; sources: Source[] }[] = [];
    messages.forEach((m, i) => {
      if (m.role === "assistant" && m.sources?.length) out.push({ id: m.id, title: messages[i - 1]?.text ?? "Answer", sources: m.sources });
    });
    return out.reverse();
  }, [messages]);
  const Item = ({ s, k }: { s: Source; k: string }) => {
    const [a, b] = parseLines(s.lines);
    return (
      <div className="border-b">
        <div className="flex items-center gap-2 px-3 py-1 hover:bg-accent/40">
          <BookOpen className="size-3.5 shrink-0 text-sky-400" />
          <button onClick={() => openFile(s.file, a, b)} className="min-w-0 truncate text-left font-mono text-[11.5px] hover:underline">{s.file}:{s.lines}</button>
          <span className="truncate text-muted-foreground">{s.symbol}</span>
          <button className="ml-auto shrink-0 text-[11px] text-primary hover:underline" onClick={() => setPeek(peek === k ? null : k)}>{peek === k ? "Hide" : "Peek"}</button>
        </div>
        {peek === k && <Peek repoId={repoId} s={s} />}
      </div>
    );
  };
  if (!groups.length && !liveHits.length) return <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground"><BookOpen className="size-6 opacity-40" />Citations from the AI’s answers show up here.</div>;
  return (
    <ScrollArea className="h-full">
      {liveHits.length > 0 && (<div><div className="bg-primary/10 px-3 py-1 text-[11px] font-medium text-primary">Reading now…</div>{liveHits.map((s, i) => <Item key={`live${i}`} s={s} k={`live${i}`} />)}</div>)}
      {groups.map((g) => (
        <div key={g.id}>
          <div className="bg-muted/40 px-3 py-1 text-[11px] font-medium"><span className="text-muted-foreground">Cited for:</span> {g.title.slice(0, 90)}</div>
          {g.sources.map((s, i) => <Item key={`${g.id}${i}`} s={s} k={`${g.id}${i}`} />)}
        </div>
      ))}
    </ScrollArea>
  );
}

// ---- Problems (review findings) -------------------------------------------------------------------
export function ProblemsPanel() {
  const messages = useIde((s) => s.messages);
  const openFile = useIde((s) => s.openFile);
  const latest = [...messages].reverse().find((m) => m.findings);
  const items: Finding[] = latest?.findings ?? [];
  if (!latest) return <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground"><AlertTriangle className="size-6 opacity-40" />Run a review to list problems here.</div>;
  const sev = { high: "destructive", medium: "warning", low: "secondary" } as const;
  return (
    <ScrollArea className="h-full">
      {latest.result?.summary && <div className="border-b px-3 py-2 text-muted-foreground">{latest.result.summary}</div>}
      {items.length === 0 && <div className="px-3 py-3 text-muted-foreground">No issues found.</div>}
      {items.map((f, i) => (
        <button key={i} onClick={() => f.file && openFile(f.file, f.line || 1)} className="flex w-full items-start gap-2 border-b px-3 py-1.5 text-left hover:bg-accent/40">
          <Badge variant={sev[f.severity]}>{f.severity}</Badge>
          <span className="min-w-0 flex-1">{f.message}</span>
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{f.file}{f.line ? `:${f.line}` : ""}{f.source === "ai" ? " · AI" : ""}</span>
        </button>
      ))}
    </ScrollArea>
  );
}

// ---- container ------------------------------------------------------------------------------------
export function BottomPanel({ repoId }: { repoId: string }) {
  const bottom = useIde((s) => s.bottom);
  const setBottom = useIde((s) => s.setBottom);
  const toggle = useIde((s) => s.toggleBottom);
  const running = useIde((s) => s.runs.some((r) => r.state === "running"));
  const lastTest = useIde((s) => s.testRuns[0]);
  const problems = useIde((s) => [...s.messages].reverse().find((m) => m.findings)?.findings?.length ?? 0);
  const sources = useIde((s) => s.messages.reduce((n, m) => n + (m.sources?.length ?? 0), 0));
  return (
    <Tabs value={bottom} onValueChange={(v) => setBottom(v as BottomTab)} className="flex h-full min-h-0 flex-col bg-panel">
      <div className="flex items-center border-b pr-2">
        <TabsList>
          <TabsTrigger value="activity"><Activity className="size-3.5" />Agent activity{running && <Loader2 className="size-3 animate-spin text-primary" />}</TabsTrigger>
          <TabsTrigger value="terminal"><TerminalSquare className="size-3.5" />Terminal</TabsTrigger>
          <TabsTrigger value="tests"><TestTube2 className="size-3.5" />Tests{lastTest && <span className={cn("size-1.5 rounded-full", lastTest.run.passed ? "bg-success" : lastTest.run.status === "no_tests" ? "bg-muted-foreground" : "bg-destructive")} />}</TabsTrigger>
          <TabsTrigger value="sources"><BookOpen className="size-3.5" />Sources{sources > 0 && <Badge variant="secondary">{sources}</Badge>}</TabsTrigger>
          <TabsTrigger value="problems"><AlertTriangle className="size-3.5" />Problems{problems > 0 && <Badge variant="warning">{problems}</Badge>}</TabsTrigger>
        </TabsList>
        <button onClick={toggle} className="ml-auto rounded p-1 text-muted-foreground hover:bg-accent" title="Hide panel"><ChevronDown className="size-4" /></button>
      </div>
      <div className="min-h-0 flex-1">
        <TabsContent value="activity" className="m-0 h-full"><ActivityPanel /></TabsContent>
        <TabsContent value="terminal" className="m-0 h-full"><TerminalPanel repoId={repoId} /></TabsContent>
        <TabsContent value="tests" className="m-0 h-full"><TestsPanel repoId={repoId} /></TabsContent>
        <TabsContent value="sources" className="m-0 h-full"><SourcesPanel repoId={repoId} /></TabsContent>
        <TabsContent value="problems" className="m-0 h-full"><ProblemsPanel /></TabsContent>
      </div>
    </Tabs>
  );
}
