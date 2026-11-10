"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { AlertCircle, Check, ChevronDown, CircleDashed, Loader2, MinusCircle, Search, Wrench, Brain, Flag } from "lucide-react";
import { toRows, currentActivity, type Row } from "@/lib/activity";
import { fmtMs, cn } from "@/lib/utils";
import type { Run } from "@/lib/types";
import { derivePhases, type PhaseInfo } from "./phases";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { FileLink } from "@/components/common/bits";
import { parseLines } from "@/lib/utils";

function useNow(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { if (!active) return; const t = window.setInterval(() => setNow(Date.now()), 500); return () => window.clearInterval(t); }, [active]);
  return now;
}

const ICON: Record<PhaseInfo["state"], React.ReactNode> = {
  done: <Check className="size-3.5" />, running: <Loader2 className="size-3.5 animate-spin" />, pending: <CircleDashed className="size-3.5" />, skipped: <MinusCircle className="size-3.5" />, error: <AlertCircle className="size-3.5" />,
};
const TONE: Record<PhaseInfo["state"], string> = {
  done: "bg-success/15 text-success", running: "bg-primary/15 text-primary ring-2 ring-primary/30", pending: "bg-secondary text-muted-foreground", skipped: "bg-secondary text-muted-foreground/60", error: "bg-destructive/15 text-destructive",
};

/** The eight-phase pipeline, driven only by real node events. */
export function PhaseStepper({ phases, vertical }: { phases: PhaseInfo[]; vertical?: boolean }) {
  return (
    <ol className={cn("flex", vertical ? "flex-col gap-0" : "items-start gap-1 overflow-x-auto pb-1")} aria-label="Agent phases">
      {phases.map((p, i) => (
        <li key={p.key} className={cn("relative flex", vertical ? "items-center gap-3 pb-3" : "min-w-[68px] flex-1 flex-col items-center gap-1.5 text-center")} aria-current={p.state === "running" ? "step" : undefined}>
          {i < phases.length - 1 && <span aria-hidden className={cn("absolute", vertical ? "left-[13px] top-7 h-[calc(100%-18px)] w-px" : "left-1/2 top-[13px] h-px w-full", p.state === "done" ? "bg-success/40" : "bg-border")} />}
          <motion.span layout className={cn("relative z-10 flex size-[27px] shrink-0 items-center justify-center rounded-full", TONE[p.state])}>{ICON[p.state]}</motion.span>
          <span className={cn("min-w-0", vertical && "flex flex-1 items-center justify-between gap-2")}>
            <span className={cn("block text-[11.5px] font-medium", p.state === "pending" || p.state === "skipped" ? "text-muted-foreground" : "text-foreground", p.state === "skipped" && "line-through decoration-muted-foreground/40")}>{p.label}</span>
            <span className="block text-[10.5px] tabular-nums text-muted-foreground">{p.state === "skipped" ? "not needed" : p.visits ? `${fmtMs(Math.round(p.ms))}${p.visits > 1 ? ` · ${p.visits}×` : ""}` : p.state === "pending" ? "waiting" : ""}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

const KIND_ICON: Record<Row["kind"], React.ReactNode> = {
  node: <Flag className="size-3.5" />, tool: <Wrench className="size-3.5" />, llm: <Brain className="size-3.5" />, step: <Search className="size-3.5" />,
  status: <Loader2 className="size-3.5" />, result: <Check className="size-3.5" />, error: <AlertCircle className="size-3.5" />, run: <Flag className="size-3.5" />,
};

function EventRow({ r }: { r: Row }) {
  const [open, setOpen] = useState(false);
  const hits = r.hits ?? [];
  return (
    <li className={cn("rounded-md px-2 py-1.5 text-xs", r.state === "error" && "bg-destructive/8", r.depth > 0 && "ml-3")}>
      <div className="flex items-start gap-2">
        <span className={cn("mt-0.5", r.state === "error" ? "text-destructive" : r.state === "running" ? "text-primary" : "text-muted-foreground")}>{r.state === "running" && r.kind !== "node" ? <Loader2 className="size-3.5 animate-spin" /> : KIND_ICON[r.kind]}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2"><span className={cn("min-w-0 truncate", r.kind === "node" ? "font-medium" : "")}>{r.title}</span>{r.ms != null && <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">{fmtMs(r.ms)}</span>}</div>
          {r.detail && <div className={cn("truncate font-mono text-[11px]", r.state === "error" ? "text-destructive" : "text-muted-foreground")} title={r.detail}>{r.detail}</div>}
          {hits.length > 0 && (
            <button onClick={() => setOpen(!open)} className="mt-1 flex items-center gap-1 text-[11px] text-primary hover:underline"><ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} />{hits.length} code hit{hits.length > 1 ? "s" : ""}</button>
          )}
          {open && <ul className="mt-1 space-y-0.5">{hits.map((h, i) => <li key={i}><FileLink path={h.file} line={parseLines(h.lines)[0]} end={parseLines(h.lines)[1]}>{h.file}:{h.lines}{h.symbol ? ` · ${h.symbol}` : ""}</FileLink></li>)}</ul>}
        </div>
      </div>
    </li>
  );
}

export function AgentTimeline({ runs, activeId, onSelect }: { runs: Run[]; activeId: string | null; onSelect: (id: string) => void }) {
  const run = runs.find((r) => r.id === activeId) ?? runs[runs.length - 1];
  const live = run?.state === "running";
  const now = useNow(!!live);
  const [showAll, setShowAll] = useState(false);
  if (!run) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <PhaseStepper phases={derivePhases(undefined)} vertical />
        <p className="text-xs text-muted-foreground">Phases fill in as the agent works. Only real events are shown.</p>
      </div>
    );
  }
  const phases = derivePhases(run, now);
  const rows = toRows(run);
  const result = [...run.events].reverse().find((e) => e.type === "result");
  const data = result && result.type === "result" ? result.data : undefined;
  const elapsed = (run.ended ?? now) - run.started;
  const errors = rows.filter((r) => r.state === "error");
  const shown = showAll ? rows : rows.filter((r) => r.kind !== "status").slice(-40);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-3 border-b p-4">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0"><div className="truncate text-[13px] font-semibold">{run.label}</div><div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground"><Badge variant={live ? "info" : run.state === "done" ? "success" : run.state === "cancelled" ? "secondary" : "destructive"} className="capitalize">{run.state}</Badge><span className="tabular-nums">{fmtMs(elapsed)}</span></div></div>
          {runs.length > 1 && <Select aria-label="Choose run" className="h-7 w-28 text-xs" value={run.id} onValueChange={onSelect} options={runs.slice().reverse().map((r, i) => ({ value: r.id, label: `${r.mode} #${runs.length - i}` }))} />}
        </div>
        {live && <div className="flex items-center gap-2 rounded-md bg-primary/8 px-2.5 py-1.5 text-xs text-primary"><Loader2 className="size-3.5 shrink-0 animate-spin" /><span className="min-w-0 truncate" title={currentActivity(run)}>{currentActivity(run)}</span></div>}
        <PhaseStepper phases={phases} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {errors.length > 0 && <div role="alert" className="mb-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">{errors.length} error{errors.length > 1 ? "s" : ""} during this run: {errors[0].detail ?? errors[0].title}</div>}
        <div className="mb-1.5 flex items-center justify-between px-1"><span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Activity</span><button className="text-[11px] text-primary hover:underline" onClick={() => setShowAll(!showAll)}>{showAll ? "Hide status lines" : "Show all events"}</button></div>
        <ul className="space-y-0.5">{shown.map((r) => <EventRow key={r.key} r={r} />)}</ul>
        {shown.length === 0 && <div className="px-2 py-6 text-center text-xs text-muted-foreground">Waiting for the first event…</div>}
      </div>
      {data && (data.usage || data.context) && (
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 border-t px-4 py-2.5 text-[11px] text-muted-foreground">
          {data.usage && <><span>Model calls</span><span className="text-right tabular-nums text-foreground">{data.usage.calls}</span><span>Tokens in / out</span><span className="text-right tabular-nums text-foreground">{data.usage.input_tokens.toLocaleString()} / {data.usage.output_tokens.toLocaleString()}</span></>}
          {data.context && <><span>Context</span><span className="text-right tabular-nums text-foreground">{data.context.kept} snippets · {data.context.tokens.toLocaleString()}/{data.context.budget.toLocaleString()} tok</span></>}
          {data.usage?.cost_usd != null && <><span>Cost</span><span className="text-right tabular-nums text-foreground">${data.usage.cost_usd.toFixed(4)}</span></>}
        </div>
      )}
    </div>
  );
}
