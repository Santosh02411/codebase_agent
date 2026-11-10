"use client";
import { useState } from "react";
import { ChevronDown, ShieldAlert } from "lucide-react";
import { cn, parseLines } from "@/lib/utils";
import type { Run, Source } from "@/lib/types";
import type { ResultData } from "@/lib/types";
import { FileLink } from "@/components/common/bits";
import { Badge } from "@/components/ui/badge";

/** Expandable evidence: the code the answer rests on, which snippets were cited, the tools the agent used, and any warnings. */
export function Evidence({ sources, result, run }: { sources: Source[]; result?: ResultData; run?: Run }) {
  const [open, setOpen] = useState(false);
  const tools = (run?.events ?? []).filter((e) => e.type === "tool" && e.phase !== "start");
  const cites = result?.citations;
  const flags = result?.context?.injection_flags ?? [];
  const refs = cites?.references;
  if (!sources.length && !tools.length && !flags.length) return null;
  return (
    <div className="rounded-lg border bg-panel">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium">
        <ChevronDown className={cn("size-3.5 text-muted-foreground transition-transform", !open && "-rotate-90")} />Evidence
        <span className="font-normal text-muted-foreground">{sources.length} snippet{sources.length === 1 ? "" : "s"}{cites ? ` · ${cites.cited.length} cited` : ""}{tools.length ? ` · ${tools.length} tool call${tools.length === 1 ? "" : "s"}` : ""}</span>
        {(cites?.invalid.length || refs?.invalid?.length) ? <Badge variant="destructive" className="ml-auto">unmatched references</Badge> : null}
        {flags.length > 0 && <Badge variant="warning" className="ml-auto gap-1"><ShieldAlert className="size-3" />injection-like text</Badge>}
      </button>
      {open && (
        <div className="space-y-3 border-t px-3 py-3 text-xs">
          {flags.length > 0 && <div role="alert" className="rounded-md border border-warning/30 bg-warning/8 px-2.5 py-2"><div className="font-medium text-warning">Text in the repository that looks like instructions to an AI was treated as data.</div>{flags.map((f) => <div key={f.cite} className="mt-1 text-muted-foreground">[{f.cite}] <FileLink path={f.file} line={parseLines(f.lines)[0]} /> “{f.examples[0]}”</div>)}</div>}
          {(refs?.invalid?.length ?? 0) > 0 && <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-destructive">These file:line references in the answer don’t match the repository: {refs!.invalid!.join(", ")}</div>}
          {sources.length > 0 && (
            <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Code the agent was shown</div>
              <ul className="space-y-0.5">{sources.map((s, i) => { const [a, b] = parseLines(s.lines); return (
                <li key={i} className="flex items-center gap-2"><span className={cn("flex size-[18px] shrink-0 items-center justify-center rounded text-[10.5px] font-semibold", s.cited ? "bg-primary/12 text-primary" : "bg-secondary text-muted-foreground")}>{s.cite ?? i + 1}</span><FileLink path={s.file} line={a} end={b}>{s.file}:{s.lines}</FileLink>{s.symbol && <span className="truncate text-muted-foreground">{s.symbol}</span>}{s.cited && <Badge variant="success" className="ml-auto">cited</Badge>}</li>); })}</ul></div>
          )}
          {tools.length > 0 && (
            <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Tools used</div>
              <ul className="space-y-0.5 font-mono text-[11px]">{tools.map((e, i) => e.type === "tool" && <li key={i} className="flex gap-2"><span className={e.phase === "error" ? "text-destructive" : "text-success"}>{e.phase === "error" ? "✗" : "✓"}</span><span>{e.name}</span><span className="truncate text-muted-foreground">{e.error ?? e.args}</span>{e.ms != null && <span className="ml-auto text-muted-foreground">{e.ms} ms</span>}</li>)}</ul></div>
          )}
        </div>
      )}
    </div>
  );
}
