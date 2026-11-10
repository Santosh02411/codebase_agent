"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Ban, FileDiff, FileCode2, ImageIcon, Loader2, RotateCcw, ScanSearch, Sparkles, User } from "lucide-react";
import { api } from "@/lib/api";
import { currentActivity } from "@/lib/activity";
import { useOpenFile } from "@/hooks/useOpen";
import { cn, parseLines } from "@/lib/utils";
import type { ChatMessage, Run } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";
import { Markdown } from "@/components/common/Markdown";
import { CopyButton, MockNotice, modelErrorHint } from "@/components/common/bits";
import { Evidence } from "./Evidence";
import { TestRunCard, VerdictBadge, VerdictBanner } from "./TestResult";
import { MODES } from "./modes";

const STATUS: Record<string, { v: "success" | "warning" | "destructive" | "secondary"; t: string }> = {
  verified: { v: "success", t: "verified" }, fix_verified: { v: "success", t: "verified" }, unverified: { v: "warning", t: "not verified" }, fix_unverified: { v: "warning", t: "not verified" },
  failed: { v: "destructive", t: "failed" }, fix_failed: { v: "destructive", t: "failed" }, no_change: { v: "secondary", t: "no change" }, no_fix: { v: "secondary", t: "no fix" },
};

function PatchCard({ patchId }: { patchId: string }) {
  const p = useQuery({ queryKey: ["patch", patchId], queryFn: () => api.patch(patchId), retry: false });
  if (p.isLoading) return <div className="h-16 animate-pulse rounded-lg bg-muted" />;
  if (!p.data) return <div className="rounded-lg border px-3 py-2 text-xs text-muted-foreground">The proposed patch is no longer available.</div>;
  const r = p.data;
  const verdict = r.checks?.verdict ?? r.verification?.verdict ?? null;
  return (
    <div className="space-y-2.5 rounded-lg border bg-panel p-3">
      <div className="flex items-center gap-2"><FileDiff className="size-4 text-primary" /><span className="min-w-0 flex-1 truncate text-[13px] font-medium">Proposed changes</span><Badge variant={r.status === "applied" ? "success" : r.status === "proposed" ? "warning" : "secondary"}>{r.status}</Badge></div>
      <ul className="space-y-0.5 text-xs">{r.files.slice(0, 6).map((f) => <li key={f.path} className="flex items-center gap-2 font-mono"><span className="truncate">{f.path}</span><span className="ml-auto shrink-0 text-success">+{f.additions}</span><span className="shrink-0 text-destructive">−{f.deletions}</span></li>)}</ul>
      <VerdictBanner v={verdict} />
      <div className="flex items-center gap-2"><Button asChild size="sm"><Link href={`/changes?patch=${r.id}`}>Review & apply</Link></Button><span className="text-[11px] text-muted-foreground">Nothing has been changed in your project yet.</span></div>
    </div>
  );
}

function UserMsg({ m }: { m: ChatMessage }) {
  const mode = MODES.find((x) => x.mode === m.mode);
  return (
    <div className="flex justify-end gap-2.5">
      <div className="max-w-[85%] space-y-1.5">
        <div className="rounded-2xl rounded-tr-md bg-primary px-3.5 py-2.5 text-[13.5px] text-primary-foreground"><div className="whitespace-pre-wrap break-words">{m.text}</div></div>
        <div className="flex flex-wrap justify-end gap-1.5 text-[11px] text-muted-foreground">
          {mode && <span className="inline-flex items-center gap-1"><mode.icon className="size-3" />{mode.label}</span>}
          {m.attachment && <span className="inline-flex items-center gap-1 font-mono"><FileCode2 className="size-3" />{m.attachment.file}:{m.attachment.startLine}-{m.attachment.endLine}</span>}
          {m.shots?.length ? <span className="inline-flex items-center gap-1"><ImageIcon className="size-3" />{m.shots.length} screenshot{m.shots.length > 1 ? "s" : ""}</span> : null}
        </div>
      </div>
      <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground"><User className="size-3.5" /></span>
    </div>
  );
}

export function AssistantMsg({ m, run, onRetry }: { m: ChatMessage; run?: Run; onRetry?: () => void }) {
  const openFile = useOpenFile();
  const d = m.result;
  const st = STATUS[m.result?.status ?? ""];
  const sources = m.sources ?? [];
  const mode = MODES.find((x) => x.mode === m.mode);
  const onCite = (n: number) => { const s = sources.find((x) => x.cite === n) ?? sources[n - 1]; if (s) { const [a, b] = parseLines(s.lines); openFile(s.file, a, b); } };
  return (
    <div className="flex gap-2.5">
      <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary"><Sparkles className="size-3.5" /></span>
      <div className="min-w-0 max-w-full flex-1 space-y-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground"><span className="font-medium text-foreground">Agent</span>{mode && <Badge variant="secondary">{mode.label}</Badge>}{st && <Badge variant={st.v}>{st.t}</Badge>}{d?.llm && <span className="truncate font-mono text-[11px]">{d.llm}</span>}</div>
        {m.state === "running" && (
          <div className="space-y-2" role="status" aria-live="polite">
            <div className="flex items-center gap-2 text-[13px] text-muted-foreground"><Loader2 className="size-4 animate-spin text-primary" /><span className="min-w-0 truncate">{currentActivity(run)}</span></div>
            <div className="space-y-1.5"><div className="h-3 w-2/3 animate-pulse rounded bg-muted" /><div className="h-3 w-1/2 animate-pulse rounded bg-muted" /></div>
          </div>
        )}
        {m.state === "error" && <div className="space-y-2"><ErrorState title="The agent couldn’t finish" error={m.error} onRetry={onRetry} className="items-start text-left" />{modelErrorHint(m.error) && <div role="note" className="rounded-lg border border-info/30 bg-info/8 px-3 py-2 text-xs leading-relaxed"><span className="font-medium text-info">What this means: </span><span className="text-muted-foreground">{modelErrorHint(m.error)}</span></div>}</div>}
        {m.state === "cancelled" && <div className="flex items-center gap-2 rounded-lg border bg-secondary/50 px-3 py-2 text-xs text-muted-foreground"><Ban className="size-3.5" />Stopped before the agent finished.{onRetry && <Button variant="ghost" size="xs" onClick={onRetry}><RotateCcw />Run again</Button>}</div>}
        {m.state === "done" && (
          <>
            <MockNotice llm={d?.llm} />
            <div className="group relative"><Markdown sources={sources} onCite={onCite}>{d?.answer || d?.summary || d?.explanation || "The agent finished without an answer."}</Markdown>
              <div className="mt-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"><CopyButton text={d?.answer ?? ""} label="Copy answer" /></div></div>
            {m.patchId && <PatchCard patchId={m.patchId} />}
            {!m.patchId && m.proposalId && d?.diff && <div className="space-y-2 rounded-lg border p-3"><div className="text-[13px] font-medium">Proposed changes (not stored as a patch)</div><VerdictBanner v={d.verification} /><Markdown>{"```diff\n" + d.diff + "\n```"}</Markdown><p className="text-[11px] text-muted-foreground">Open the IDE view to review and apply this proposal.</p></div>}
            {m.findings && m.findings.length > 0 && <div className="flex items-center gap-3 rounded-lg border bg-panel px-3 py-2.5"><ScanSearch className="size-4 text-primary" /><span className="text-[13px]">{m.findings.length} review finding{m.findings.length > 1 ? "s" : ""}</span><Button asChild size="sm" variant="outline" className="ml-auto"><Link href="/review">Open in Code Review</Link></Button></div>}
            {(d?.test_before || d?.test_after) && <div className="space-y-1.5"><div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Test results {d?.verification && <VerdictBadge v={d.verification} />}</div><TestRunCard title="Before the change" run={d?.test_before} /><TestRunCard title="After the change" run={d?.test_after} /></div>}
            <Evidence sources={sources} result={d} run={run} />
          </>
        )}
      </div>
    </div>
  );
}

export function MessageList({ messages, runs, onRetry }: { messages: ChatMessage[]; runs: Run[]; onRetry: (m: ChatMessage) => void }) {
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6" aria-live="off">
      {messages.map((m) => (
        <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className={cn("min-w-0")}>
          {m.role === "user" ? <UserMsg m={m} /> : <AssistantMsg m={m} run={runs.find((r) => r.id === m.runId)} onRetry={() => onRetry(m)} />}
        </motion.div>
      ))}
    </div>
  );
}
