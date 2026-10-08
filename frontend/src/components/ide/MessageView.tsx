"use client";
import { AlertCircle, FileDiff, Loader2, OctagonX, Paperclip } from "lucide-react";
import { counts } from "@/lib/edits";
import { currentActivity } from "@/lib/activity";
import { parseLines } from "@/lib/utils";
import type { ChatMessage, Finding, Source } from "@/lib/types";
import { useIde } from "@/store/ide";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Markdown } from "./Markdown";
import { TestPill } from "./DiffViews";

export function SourceChips({ sources, max = 8 }: { sources: Source[]; max?: number }) {
  const openFile = useIde((s) => s.openFile);
  const setBottom = useIde((s) => s.setBottom);
  if (!sources.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {sources.slice(0, max).map((s, i) => {
        const [a, b] = parseLines(s.lines);
        return (
          <button key={`${s.file}:${s.lines}:${i}`} onClick={() => openFile(s.file, a, b)} title={s.symbol}
            className="max-w-full truncate rounded border bg-background px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground hover:border-primary hover:text-foreground">
            {s.file.split("/").pop()}:{s.lines}
          </button>
        );
      })}
      {sources.length > max && <button onClick={() => setBottom("sources")} className="px-1 text-[11px] text-primary hover:underline">+{sources.length - max} more</button>}
    </div>
  );
}

function Findings({ items }: { items: Finding[] }) {
  const openFile = useIde((s) => s.openFile);
  const setBottom = useIde((s) => s.setBottom);
  const sev = { high: "destructive", medium: "warning", low: "secondary" } as const;
  return (
    <div className="mt-2 space-y-1.5">
      {items.slice(0, 5).map((f, i) => (
        <button key={i} onClick={() => f.file && openFile(f.file, f.line || 1)} className="block w-full rounded-md border bg-background p-2 text-left hover:border-primary">
          <div className="flex items-center gap-1.5"><Badge variant={sev[f.severity]}>{f.severity}</Badge><span className="truncate font-mono text-[11px]">{f.file}{f.line ? `:${f.line}` : ""}</span></div>
          <div className="mt-1 text-[12px]">{f.message}</div>
        </button>
      ))}
      {items.length > 5 && <button className="text-[11px] text-primary hover:underline" onClick={() => setBottom("problems")}>See all {items.length} in Problems</button>}
      {items.length === 0 && <div className="text-muted-foreground">No issues found.</div>}
    </div>
  );
}

function ProposalCard({ id }: { id: string }) {
  const p = useIde((s) => s.proposals[id]);
  const openReview = useIde((s) => s.openReview);
  if (!p) return null;
  const c = counts(p);
  const files = new Set([...p.edits.map((e) => e.file), ...p.newFiles.map((n) => n.path)]);
  return (
    <div className="mt-2 rounded-lg border bg-background p-2.5">
      <div className="flex items-center gap-2 font-medium"><FileDiff className="size-4 text-primary" />{c.total} change{c.total === 1 ? "" : "s"} in {files.size} file{files.size === 1 ? "" : "s"}
        {p.applied && <Badge variant="success" className="ml-auto">applied</Badge>}{p.discarded && <Badge variant="secondary" className="ml-auto">discarded</Badge>}
        {!p.applied && !p.discarded && c.accepted + c.rejected > 0 && <Badge variant="secondary" className="ml-auto">{c.accepted} approved · {c.rejected} rejected</Badge>}
      </div>
      <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{[...files].join(", ")}</div>
      {(p.testBefore || p.testAfter) && <div className="mt-1.5 flex flex-wrap gap-3 text-[11px]"><TestPill t={p.testBefore} label="Tests before" /><TestPill t={p.testAfter} label="after" /></div>}
      <Button size="sm" className="mt-2" onClick={() => openReview(id)}>{p.applied || p.discarded ? "View changes" : "Review & approve"}</Button>
    </div>
  );
}

const STATUS_BADGE: Record<string, { v: "success" | "destructive" | "warning" | "secondary"; t: string }> = {
  fix_verified: { v: "success", t: "fix verified by tests" }, verified: { v: "success", t: "verified by tests" },
  fix_failed: { v: "destructive", t: "tests fail after fix" }, failed: { v: "destructive", t: "tests fail after change" },
  fix_unverified: { v: "warning", t: "not verified" }, unverified: { v: "warning", t: "not verified" },
  no_fix: { v: "secondary", t: "no fix produced" }, no_change: { v: "secondary", t: "no change produced" },
};

export function MessageView({ m }: { m: ChatMessage }) {
  const run = useIde((s) => s.runs.find((r) => r.id === m.runId));
  const openFile = useIde((s) => s.openFile);
  const setBottom = useIde((s) => s.setBottom);

  if (m.role === "user") {
    return (
      <div className="ml-6 rounded-lg bg-primary/15 px-3 py-2">
        {m.attachment && (
          <button onClick={() => openFile(m.attachment!.file, m.attachment!.startLine, m.attachment!.endLine)} className="mb-1.5 flex max-w-full items-center gap-1 rounded border bg-background/60 px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground hover:text-foreground">
            <Paperclip className="size-3 shrink-0" /><span className="truncate">{m.attachment.file}:{m.attachment.startLine}-{m.attachment.endLine}</span>
          </button>
        )}
        <div className="whitespace-pre-wrap break-words">{m.text}</div>
      </div>
    );
  }

  if (m.state === "running") {
    const tools = run?.events.filter((e) => e.type === "tool" && e.phase === "end").length ?? 0;
    return (
      <div className="rounded-lg border bg-panel px-3 py-2.5">
        <div className="flex items-center gap-2"><Loader2 className="size-4 animate-spin text-primary" /><span className="truncate">{currentActivity(run)}</span></div>
        <button onClick={() => setBottom("activity")} className="mt-1 text-[11px] text-primary hover:underline">{tools} tool call{tools === 1 ? "" : "s"} so far · watch live</button>
      </div>
    );
  }
  if (m.state === "error") return <div className="flex gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-destructive"><AlertCircle className="mt-0.5 size-4 shrink-0" /><span className="break-words">{m.error}</span></div>;
  if (m.state === "cancelled") return <div className="flex items-center gap-2 rounded-lg border px-3 py-2 text-muted-foreground"><OctagonX className="size-4" />Stopped. The server may finish the request in the background; nothing was applied.</div>;

  const r = m.result;
  if (!r) return null;
  const body = r.answer ?? (m.mode === "review" ? r.summary : r.explanation) ?? "";
  const status = r.status ? STATUS_BADGE[r.status] : undefined;
  const hasProposal = !!m.proposalId;
  const showMockHint = r.llm === "mock" && (r.status === "no_fix" || r.status === "no_change");
  return (
    <div className="rounded-lg border bg-panel px-3 py-2.5">
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
        {r.llm && <Badge variant="outline">{r.llm} model</Badge>}
        {status && <Badge variant={status.v}>{status.t}</Badge>}
      </div>
      {body && <Markdown>{body}</Markdown>}
      {!body && hasProposal && <div className="text-muted-foreground">The agent proposed a change.</div>}
      {!body && !hasProposal && !m.findings && <div className="text-muted-foreground">The agent produced no text for this request.</div>}
      {showMockHint && <div className="mt-2 rounded border border-warning/40 bg-warning/10 px-2 py-1.5 text-[12px]">The offline mock model only searches code. Set <code>LLM_PROVIDER</code> and an API key in <code>.env</code> to generate changes.</div>}
      {m.findings && <Findings items={m.findings} />}
      {m.proposalId && <ProposalCard id={m.proposalId} />}
      {m.sources && m.sources.length > 0 && (<><div className="mt-2.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Sources</div><SourceChips sources={m.sources} /></>)}
    </div>
  );
}
