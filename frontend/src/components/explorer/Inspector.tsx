"use client";
import { useState } from "react";
import { ArrowDownLeft, ArrowUpRight, Box, FunctionSquare, Braces, FlaskConical, Search, Variable } from "lucide-react";
import { useFileSymbols, useImpact, useModuleGraph, useSemanticSearch, useSymbolDetail, useTextSearch } from "@/hooks/queries";
import { cn } from "@/lib/utils";
import type { SymbolInfo, SymbolRef } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/misc";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FileLink } from "@/components/common/bits";

const KIND_ICON = (k: string) => k === "class" || k === "struct" || k === "interface" || k === "enum" ? <Box className="size-3.5 text-chart-4" /> : k === "variable" ? <Variable className="size-3.5 text-muted-foreground" /> : k === "test" ? <FlaskConical className="size-3.5 text-success" /> : <FunctionSquare className="size-3.5 text-chart-1" />;

export function Inspector({ repoId, file, symbolAtCursor, onOpen }: { repoId: string; file?: string; symbolAtCursor?: SymbolInfo | null; onOpen: (path: string, line?: number, end?: number) => void }) {
  const [tab, setTab] = useState("outline");
  const [picked, setPicked] = useState<string | undefined>();
  const symbols = useFileSymbols(repoId, file);
  const activeSym = picked ?? symbolAtCursor?.id;
  return (
    <Tabs value={tab} onValueChange={setTab} className="flex h-full min-h-0 flex-col">
      <TabsList className="shrink-0 border-b px-2 pt-1">
        {[["outline", "Outline"], ["refs", "References"], ["related", "Related"], ["search", "Search"]].map(([v, l]) => <TabsTrigger key={v} value={v}>{l}</TabsTrigger>)}
      </TabsList>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <TabsContent value="outline" className="p-2">
          {!file ? <EmptyState className="py-10" title="No file open" description="Open a file to see its functions and classes." />
            : symbols.isLoading ? <div className="space-y-1.5">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-6" />)}</div>
            : symbols.isError ? <ErrorState error={symbols.error} onRetry={() => symbols.refetch()} />
            : !symbols.data?.length ? <EmptyState className="py-10" icon={<Braces className="size-5" />} title="No symbols found" description="This file has no functions or classes, or its language isn’t parsed." />
            : <ul>{symbols.data.map((s) => (
                <li key={s.id}><button onClick={() => { setPicked(s.id); onOpen(s.file, s.start, s.end); setTab("refs"); }} className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[13px] hover:bg-accent/60", activeSym === s.id && "bg-accent")}>
                  {KIND_ICON(s.kind)}<span className="truncate">{s.qualname}</span><span className="ml-auto font-mono text-[11px] text-muted-foreground">{s.start}</span></button></li>))}</ul>}
        </TabsContent>
        <TabsContent value="refs" className="p-3"><Refs repoId={repoId} id={activeSym} onOpen={onOpen} /></TabsContent>
        <TabsContent value="related" className="p-3"><Related repoId={repoId} file={file} onOpen={onOpen} /></TabsContent>
        <TabsContent value="search" className="p-3"><SearchPane repoId={repoId} onOpen={onOpen} /></TabsContent>
      </div>
    </Tabs>
  );
}

function RefList({ title, icon, items, onOpen }: { title: string; icon: React.ReactNode; items: SymbolRef[]; onOpen: (p: string, l?: number, e?: number) => void }) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{icon}{title}<span className="tabular-nums">({items.length})</span></div>
      {items.length === 0 ? <div className="px-1 pb-2 text-xs text-muted-foreground">None found.</div> : (
        <ul className="mb-3 space-y-0.5">{items.map((r) => <li key={r.id}><button onClick={() => onOpen(r.file, r.start, r.end)} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] hover:bg-accent/60"><span className="truncate">{r.qualname}</span>{r.confidence !== "exact" && r.confidence && <Badge variant="outline" title="Resolved by static analysis; may be a name-based guess">{r.confidence}</Badge>}<span className="ml-auto max-w-[45%] truncate font-mono text-[11px] text-muted-foreground">{r.file}:{r.start}</span></button></li>)}</ul>
      )}
    </div>
  );
}

function Refs({ repoId, id, onOpen }: { repoId: string; id?: string; onOpen: (p: string, l?: number, e?: number) => void }) {
  const d = useSymbolDetail(repoId, id);
  if (!id) return <EmptyState className="py-10" title="Pick a symbol" description="Choose a function or class in the Outline, or place the cursor inside one, to see who calls it and what it depends on." />;
  if (d.isLoading) return <div className="space-y-2"><Skeleton className="h-16" /><Skeleton className="h-24" /></div>;
  if (d.isError) return <ErrorState error={d.error} onRetry={() => d.refetch()} />;
  const s = d.data!;
  return (
    <div>
      <div className="mb-3 rounded-lg bg-surface p-2.5"><div className="flex items-center gap-2 text-[13px] font-semibold">{KIND_ICON(s.kind)}{s.qualname}<Badge variant="secondary">{s.kind}</Badge></div>
        {s.signature && <code className="mt-1 block break-words font-mono text-[11.5px] text-muted-foreground">{s.signature}</code>}
        {s.route && <Badge variant="info" className="mt-1.5">{s.route}</Badge>}
        {s.doc && <p className="mt-1.5 line-clamp-4 text-xs text-muted-foreground">{s.doc}</p>}</div>
      <RefList title="Callers" icon={<ArrowDownLeft className="size-3" />} items={s.callers} onOpen={onOpen} />
      <RefList title="Calls" icon={<ArrowUpRight className="size-3" />} items={s.callees} onOpen={onOpen} />
      {s.base_symbols.length > 0 && <RefList title="Extends" icon={<ArrowUpRight className="size-3" />} items={s.base_symbols} onOpen={onOpen} />}
      {s.derived.length > 0 && <RefList title="Subclasses" icon={<ArrowDownLeft className="size-3" />} items={s.derived} onOpen={onOpen} />}
      {s.unresolved_calls.length > 0 && <div className="text-[11px] text-muted-foreground">Unresolved calls (external or dynamic): {s.unresolved_calls.slice(0, 8).join(", ")}{s.unresolved_calls.length > 8 ? "…" : ""}</div>}
    </div>
  );
}

function Related({ repoId, file, onOpen }: { repoId: string; file?: string; onOpen: (p: string, l?: number, e?: number) => void }) {
  const impact = useImpact(repoId, file);
  const mods = useModuleGraph(repoId, file, 1, "both", !!file);
  if (!file) return <EmptyState className="py-10" title="No file open" />;
  if (impact.isLoading || mods.isLoading) return <div className="space-y-2"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>;
  const imports = (mods.data?.edges ?? []).filter((e) => e.source === file).map((e) => e.target);
  const importedBy = (mods.data?.edges ?? []).filter((e) => e.target === file).map((e) => e.source);
  const sect = (title: string, items: string[], badge?: (i: string) => React.ReactNode) => (
    <div className="mb-3"><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{title} <span className="tabular-nums">({items.length})</span></div>
      {items.length === 0 ? <div className="text-xs text-muted-foreground">None.</div> : <ul className="space-y-0.5">{items.slice(0, 40).map((f) => <li key={f} className="flex items-center gap-2"><FileLink path={f} />{badge?.(f)}</li>)}</ul>}</div>
  );
  return (
    <div>
      {sect("Imports", imports)}
      {sect("Imported by", importedBy)}
      {sect("Impact: files that depend on this one", (impact.data?.dependents ?? []).map((d) => d.file), (f) => <Badge variant="outline">distance {impact.data?.dependents.find((d) => d.file === f)?.distance}</Badge>)}
      {sect("Tests that exercise it", impact.data?.tests ?? [])}
      <button className="text-xs text-primary hover:underline" onClick={() => onOpen(file)}>Back to {file.split("/").pop()}</button>
    </div>
  );
}

function SearchPane({ repoId, onOpen }: { repoId: string; onOpen: (p: string, l?: number, e?: number) => void }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<"text" | "semantic">("text");
  const text = useTextSearch(repoId, kind === "text" ? q : "", false, false);
  const sem = useSemanticSearch(repoId, kind === "semantic" ? q : "");
  const grouped = (() => { const m = new Map<string, NonNullable<typeof text.data>["matches"]>(); for (const x of text.data?.matches ?? []) m.set(x.file, [...(m.get(x.file) ?? []), x]); return [...m.entries()]; })();
  return (
    <div className="space-y-2.5">
      <div className="relative"><Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={kind === "text" ? "Exact text across files…" : "Describe what you’re looking for…"} aria-label="Search the repository" className="pl-8" /></div>
      <Segmented size="sm" value={kind} onChange={setKind} options={[{ value: "text", label: "Text" }, { value: "semantic", label: "Semantic (AI index)" }]} />
      {q.length < 2 ? <p className="text-xs text-muted-foreground">Type at least two characters.</p> : kind === "text" ? (
        text.isLoading ? <Skeleton className="h-20" /> : text.isError ? <ErrorState error={text.error} /> : grouped.length === 0 ? <p className="text-xs text-muted-foreground">No matches.</p> : (
          <div className="space-y-2">{grouped.map(([f, ms]) => <div key={f}><FileLink path={f} /><ul>{ms.slice(0, 6).map((m) => <li key={m.line}><button onClick={() => onOpen(f, m.line)} className="flex w-full gap-2 rounded px-1.5 py-0.5 text-left font-mono text-[11.5px] hover:bg-accent/60"><span className="w-8 shrink-0 text-right text-muted-foreground">{m.line}</span><span className="truncate">{m.text}</span></button></li>)}</ul></div>)}{text.data?.truncated && <p className="text-[11px] text-muted-foreground">Showing the first matches only.</p>}</div>
        )
      ) : sem.isLoading ? <Skeleton className="h-20" /> : sem.isError ? <ErrorState error={sem.error} /> : (
        <ul className="space-y-1">{(sem.data ?? []).map((c) => <li key={c.id}><button onClick={() => onOpen(c.file, c.start, c.end)} className="w-full rounded-md px-2 py-1.5 text-left hover:bg-accent/60"><div className="flex items-center gap-2 text-[13px]"><span className="truncate font-medium">{c.qualname || c.name}</span>{c.score != null && <Badge variant="outline">{c.score.toFixed(2)}</Badge>}</div><div className="truncate font-mono text-[11px] text-muted-foreground">{c.file}:{c.start}-{c.end}</div>{c.why && <div className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{c.why}</div>}</button></li>)}</ul>
      )}
    </div>
  );
}
