"use client";
import { useEffect, useMemo, useState } from "react";
import { CaseSensitive, Regex, Sparkles, TextSearch } from "lucide-react";
import { useSemanticSearch, useTextSearch } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { FileIcon } from "./Explorer";

function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

export function SearchPanel({ repoId }: { repoId: string }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<"text" | "semantic">("text");
  const [regex, setRegex] = useState(false);
  const [caseS, setCaseS] = useState(false);
  const dq = useDebounced(q.trim());
  const text = useTextSearch(repoId, kind === "text" ? dq : "", regex, caseS);
  const sem = useSemanticSearch(repoId, kind === "semantic" ? dq : "");
  const openFile = useIde((s) => s.openFile);

  const grouped = useMemo(() => {
    const m = new Map<string, NonNullable<typeof text.data>["matches"]>();
    for (const x of text.data?.matches ?? []) m.set(x.file, [...(m.get(x.file) ?? []), x]);
    return [...m.entries()];
  }, [text.data]);

  const Toggle = ({ on, onClick, title, children }: { on: boolean; onClick: () => void; title: string; children: React.ReactNode }) => (
    <button title={title} onClick={onClick} className={cn("rounded p-1 text-muted-foreground hover:bg-accent", on && "bg-primary/20 text-primary")}>{children}</button>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="px-3 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Search</div>
      <div className="space-y-2 px-2 pb-2">
        <div className="relative">
          <Input autoFocus placeholder={kind === "text" ? "Find in repository…" : "Describe what you're looking for…"} value={q} onChange={(e) => setQ(e.target.value)} className="pr-16" />
          {kind === "text" && (
            <div className="absolute right-1 top-1 flex">
              <Toggle on={caseS} onClick={() => setCaseS(!caseS)} title="Match case"><CaseSensitive className="size-4" /></Toggle>
              <Toggle on={regex} onClick={() => setRegex(!regex)} title="Regular expression"><Regex className="size-4" /></Toggle>
            </div>
          )}
        </div>
        <div className="flex gap-1 text-[11px]">
          <button onClick={() => setKind("text")} className={cn("flex flex-1 items-center justify-center gap-1 rounded px-2 py-1", kind === "text" ? "bg-accent" : "text-muted-foreground hover:bg-accent/50")}><TextSearch className="size-3" /> Text</button>
          <button onClick={() => setKind("semantic")} className={cn("flex flex-1 items-center justify-center gap-1 rounded px-2 py-1", kind === "semantic" ? "bg-accent" : "text-muted-foreground hover:bg-accent/50")}><Sparkles className="size-3" /> Semantic (AI index)</button>
        </div>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {kind === "text" && (
          <div className="pb-4">
            {text.error && <div className="px-3 py-2 text-destructive">{(text.error as Error).message}</div>}
            {text.data && <div className="px-3 pb-1 text-muted-foreground">{text.data.matches.length}{text.data.truncated ? "+" : ""} results in {text.data.files} files</div>}
            {grouped.map(([file, ms]) => (
              <div key={file}>
                <div className="flex items-center gap-1.5 bg-muted/40 px-3 py-1 font-medium"><FileIcon name={file} /><span className="truncate">{file}</span><Badge variant="secondary" className="ml-auto">{ms.length}</Badge></div>
                {ms.map((m) => (
                  <button key={`${m.line}:${m.col}`} onClick={() => openFile(file, m.line)} className="flex w-full gap-2 px-3 py-0.5 text-left hover:bg-accent/60">
                    <span className="w-8 shrink-0 text-right text-muted-foreground">{m.line}</span>
                    <span className="truncate font-mono text-[11px]">{m.text}</span>
                  </button>
                ))}
              </div>
            ))}
            {dq.length >= 2 && text.data && text.data.matches.length === 0 && <div className="px-3 py-2 text-muted-foreground">No results.</div>}
          </div>
        )}
        {kind === "semantic" && (
          <div className="pb-4">
            {sem.error && <div className="px-3 py-2 text-destructive">{(sem.error as Error).message}</div>}
            {sem.isFetching && <div className="px-3 py-1 text-muted-foreground">Searching…</div>}
            {sem.data?.map((h) => (
              <button key={h.id} onClick={() => openFile(h.file, h.start, h.end)} className="block w-full border-b px-3 py-2 text-left hover:bg-accent/60">
                <div className="flex items-center gap-1.5"><FileIcon name={h.file} /><span className="truncate font-medium">{h.qualname}</span>{h.score != null && <Badge variant="outline" className="ml-auto">{h.score}</Badge>}</div>
                <div className="truncate text-[11px] text-muted-foreground">{h.file}:{h.start}-{h.end}{h.route ? ` · ${h.route}` : ""}</div>
                <pre className="mt-1 max-h-16 overflow-hidden whitespace-pre-wrap font-mono text-[10.5px] text-muted-foreground">{h.text.slice(0, 220)}</pre>
              </button>
            ))}
            {dq.length >= 2 && sem.data?.length === 0 && <div className="px-3 py-2 text-muted-foreground">No matches.</div>}
          </div>
        )}
        {dq.length < 2 && <div className="px-3 py-2 text-muted-foreground">Type at least two characters.</div>}
      </ScrollArea>
    </div>
  );
}
