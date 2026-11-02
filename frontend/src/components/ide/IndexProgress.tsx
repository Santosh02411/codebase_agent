"use client";
import { Loader2 } from "lucide-react";
import { useActiveIndexing } from "@/hooks/queries";
import type { IndexReport, IndexStatus } from "@/lib/types";
import { fmtMs } from "@/lib/utils";

const PHASE: Record<string, string> = {
  cloning: "Cloning repository", scanning: "Scanning files", parsing: "Parsing code into symbols", graph: "Building call & dependency graphs",
  embedding: "Embedding code for search", saving: "Saving index", ready: "Ready",
};

export function ProgressBar({ status }: { status: IndexStatus }) {
  const pct = status.total ? Math.min(100, Math.round(((status.done ?? 0) / status.total) * 100)) : undefined;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2"><Loader2 className="size-3.5 animate-spin text-primary" /><span>{PHASE[status.phase ?? ""] ?? status.phase ?? "Working"}…</span>
        {pct !== undefined && <span className="ml-auto text-muted-foreground">{status.done}/{status.total}</span>}</div>
      <div className="h-1.5 overflow-hidden rounded bg-secondary"><div className={pct === undefined ? "h-full w-1/3 animate-pulse rounded bg-primary" : "h-full rounded bg-primary transition-all"} style={pct === undefined ? undefined : { width: `${pct}%` }} /></div>
    </div>
  );
}

/** Progress of whatever is being indexed right now (single-user server: at most one at a time). */
export function ActiveProgress() {
  const active = useActiveIndexing();
  const st = Object.values(active.data ?? {}).find((s) => s.state === "indexing");
  return st ? <ProgressBar status={st} /> : null;
}

export function ReportLine({ r }: { r?: IndexReport }) {
  if (!r) return null;
  const touched = r.files_added + r.files_changed + r.files_removed;
  return (
    <div className="text-[11px] text-muted-foreground">
      {r.mode === "incremental"
        ? <>Incremental: <b className="text-foreground">{touched}</b> file{touched === 1 ? "" : "s"} reprocessed, {r.files_unchanged} reused · {r.chunks_embedded} chunk{r.chunks_embedded === 1 ? "" : "s"} embedded, {r.chunks_reused} reused</>
        : <>Full index: {r.files_total} files, {r.chunks_total} chunks</>}
      {" · "}{fmtMs(r.duration_ms)}
    </div>
  );
}
