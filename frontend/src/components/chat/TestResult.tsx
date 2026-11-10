"use client";
import { useState } from "react";
import { ChevronDown, CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import { fmtMs, cn } from "@/lib/utils";
import type { TestRun, Verdict } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

const V: Record<Verdict["status"], { variant: "success" | "warning" | "destructive"; label: string; sub: string }> = {
  resolved: { variant: "success", label: "Verified fix", sub: "A regression test failed before the change and passes after it." },
  no_regressions: { variant: "success", label: "No regressions", sub: "No new test failures and no new blocking lint errors." },
  partial: { variant: "warning", label: "Partially resolved", sub: "Some failures remain." },
  unverified: { variant: "warning", label: "Suggested fix · not verified", sub: "Nothing demonstrated that the problem is fixed." },
  not_resolved: { variant: "destructive", label: "Not resolved", sub: "The change did not fix the problem or broke something." },
};

export function VerdictBadge({ v, className }: { v?: Verdict | null; className?: string }) {
  if (!v) return <Badge variant="secondary" className={className}>Not verified</Badge>;
  const x = V[v.status];
  return <Badge variant={x.variant} className={className} title={v.summary}>{x.label}</Badge>;
}

/** The verdict with its reason, spelled out. A fix is only "verified" when the backend said so. */
export function VerdictBanner({ v }: { v?: Verdict | null }) {
  if (!v) return <div className="flex items-start gap-2.5 rounded-lg border bg-secondary/50 px-3 py-2.5 text-xs"><TriangleAlert className="mt-0.5 size-4 text-warning" /><div><div className="font-medium">Suggested fix · not verified</div><div className="text-muted-foreground">No verification result is attached to this change: tests were not run (the sandbox may be unavailable, or verification was switched off).</div></div></div>;
  const x = V[v.status];
  const tone = x.variant === "success" ? "border-success/30 bg-success/8" : x.variant === "warning" ? "border-warning/30 bg-warning/8" : "border-destructive/30 bg-destructive/8";
  return (
    <div className={cn("flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-xs", tone)}>
      {x.variant === "success" ? <CircleCheck className="mt-0.5 size-4 text-success" /> : x.variant === "warning" ? <TriangleAlert className="mt-0.5 size-4 text-warning" /> : <CircleX className="mt-0.5 size-4 text-destructive" />}
      <div className="min-w-0"><div className="text-[13px] font-semibold">{x.label}</div><div className="text-muted-foreground">{v.summary}</div>
        {v.reasons?.filter(Boolean).length > 0 && <ul className="mt-1 list-disc pl-4 text-muted-foreground">{v.reasons.filter(Boolean).slice(0, 4).map((r, i) => <li key={i} className="break-words">{r}</li>)}</ul>}</div>
    </div>
  );
}

export function TestRunCard({ run, title }: { run?: TestRun | null; title: string }) {
  const [open, setOpen] = useState(false);
  if (!run) return <div className="rounded-lg border px-3 py-2 text-xs text-muted-foreground"><span className="font-medium text-foreground">{title}:</span> not run</div>;
  const tone = run.passed ? "success" : run.status === "failed" ? "destructive" : "warning";
  return (
    <div className="rounded-lg border">
      <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className={cn("size-2 rounded-full", tone === "success" ? "bg-success" : tone === "destructive" ? "bg-destructive" : "bg-warning")} />
        <span className="font-medium">{title}</span><Badge variant={tone} className="capitalize">{run.status.replace(/_/g, " ")}</Badge>
        <span className="min-w-0 flex-1 truncate text-muted-foreground">{run.summary}</span>{run.duration_ms != null && <span className="text-muted-foreground">{fmtMs(run.duration_ms)}</span>}
        <ChevronDown className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-2 border-t p-3">
          {run.command && <div className="font-mono text-[11px] text-muted-foreground">$ {run.command}</div>}
          {run.failed_tests && run.failed_tests.length > 0 && <ul className="space-y-1">{run.failed_tests.slice(0, 12).map((t) => <li key={t.id} className="rounded bg-destructive/8 px-2 py-1 font-mono text-[11px] text-destructive">✗ {t.id}{t.message ? ` — ${t.message}` : ""}</li>)}</ul>}
          {run.output && <pre className="max-h-56 overflow-auto rounded-md bg-surface p-2 font-mono text-[11px] leading-relaxed">{run.output.slice(-4000)}</pre>}
        </div>
      )}
    </div>
  );
}
