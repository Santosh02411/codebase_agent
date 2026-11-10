"use client";
import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { AlertTriangle, ChevronDown, CircleCheck, Clipboard, Download, FileCode2, Wand2, FolderSync, Info, Loader2, Play, RefreshCw, ScanSearch, ShieldCheck, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { API_URL, api } from "@/lib/api";
import { Dropdown, DropdownContent, DropdownItem, DropdownTrigger } from "@/components/ui/dropdown";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PasteReview } from "./PasteReview";
import { useAgentRun } from "@/hooks/useAgentRun";
import { currentActivity } from "@/lib/activity";
import { useHealth, useInvalidateRepo } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { cn, fmtMs } from "@/lib/utils";
import type { StaticFinding, StaticReview } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Input } from "@/components/ui/input";
import { PageHeader, Stat } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { FileLink, MockNotice, SeverityBadge } from "@/components/common/bits";
import { ago } from "@/components/shell/IndexStatus";

export const CATS: Record<string, { label: string; hint: string }> = {
  syntax: { label: "Syntax errors", hint: "The file cannot be parsed: missing/extra brackets, colons, quotes, bad indentation" },
  "name-error": { label: "Names & typos", hint: "Undefined names, misspelled variables, attributes and module members" },
  "import-error": { label: "Imports", hint: "Importing a name or module that does not exist in the project" },
  "call-error": { label: "Calls", hint: "Wrong number of arguments, unknown keyword arguments, missing self" },
  "bug-risk": { label: "Bug risks", hint: "Code that is valid but almost certainly wrong or dangerous" },
  security: { label: "Security", hint: "Injection, unsafe deserialization, weak crypto, hard-coded secrets" },
  unused: { label: "Unused code", hint: "Unused imports and variables" },
  style: { label: "Style notes", hint: "Low-priority style observations" },
};
const QUIET = new Set(["unused", "style"]);

function Excerpt({ f }: { f: StaticFinding }) {
  const width = Math.max(1, (f.end_col || f.col + 1) - f.col);
  return (
    <pre className="overflow-x-auto rounded-lg border bg-surface p-0 font-mono text-[12px] leading-relaxed">
      {f.context.map((c) => (
        <div key={c.n}>
          <div className={cn("flex gap-3 px-3", c.n === f.line && "bg-destructive/10")}><span className="w-9 shrink-0 select-none text-right text-muted-foreground">{c.n}</span><span className="whitespace-pre">{c.text || " "}</span></div>
          {c.n === f.line && <div className="flex gap-3 px-3 text-destructive"><span className="w-9 shrink-0" /><span className="whitespace-pre font-bold">{" ".repeat(f.col)}{"^".repeat(Math.min(width, 60))}</span></div>}
        </div>
      ))}
    </pre>
  );
}

export function Item({ f, defaultOpen }: { f: StaticFinding; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const router = useRouter();
  const fixWithAi = () => { useIde.setState({ attachment: { file: f.file, startLine: f.line, endLine: f.line, text: f.evidence || f.message }, mode: "change" }); router.push("/chat"); };
  return (
    <li className="border-b last:border-0">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-start gap-3 px-4 py-2.5 text-left hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/60">
        <SeverityBadge s={f.severity} />
        <span className="min-w-0 flex-1"><span className="block break-words text-[13px]">{f.message}</span><span className="mt-0.5 block font-mono text-[11px] text-muted-foreground">line {f.line}, column {f.col + 1}</span></span>
        <Badge variant="outline" className="hidden font-mono sm:inline-flex">{f.rule}</Badge>
        {f.confidence !== "high" && <Badge variant="warning" title="The rule cannot be fully sure here">{f.confidence} confidence</Badge>}
        <ChevronDown className={cn("mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-2.5 bg-surface/40 px-4 pb-4 pt-1 pl-[4.5rem]">
          <Excerpt f={f} />
          {f.fix && <div className="rounded-lg border border-success/25 bg-success/6 px-3 py-2 text-xs leading-relaxed"><span className="font-medium">How to fix: </span>{f.fix}</div>}
          <div className="flex flex-wrap items-center gap-2"><FileLink path={f.file} line={f.line} className="border" /><Button size="xs" variant="outline" onClick={fixWithAi}><Wand2 />Fix with AI</Button><span className="text-[11px] text-muted-foreground">{CATS[f.category]?.label ?? f.category} · {f.language}</span></div>
        </div>
      )}
    </li>
  );
}

function toMarkdown(r: StaticReview, name: string): string {
  const L = [`# Code review: ${name}`, "", `${r.summary.total} finding(s) in ${r.coverage.files_analysed} files (${r.summary.by_severity.high ?? 0} high, ${r.summary.by_severity.medium ?? 0} medium, ${r.summary.by_severity.low ?? 0} low). Engine ${r.engine}, ${r.duration_ms} ms.`, ""];
  for (const f of r.findings) L.push(`- **${f.severity.toUpperCase()}** \`${f.file}:${f.line}:${f.col + 1}\` [${f.rule}] ${f.message}${f.fix ? ` — fix: ${f.fix}` : ""}`);
  return L.join("\n");
}

export function ReviewPage({ repoId }: { repoId: string }) {
  const qc = useQueryClient();
  const invalidate = useInvalidateRepo();
  const health = useHealth();
  const { run, stop } = useAgentRun();
  const messages = useIde((s) => s.messages);
  const runs = useIde((s) => s.runs);
  const [tab, setTab] = useState("project");
  useEffect(() => { if (new URLSearchParams(window.location.search).get("tab") === "paste") setTab("paste"); }, []);   // read after mount: no hydration mismatch
  const [syncing, setSyncing] = useState(false);
  const [sev, setSev] = useState<Set<string>>(new Set(["high", "medium", "low"]));
  const [cat, setCat] = useState<string>("all");
  const [quiet, setQuiet] = useState(false);
  const [q, setQ] = useState("");
  const [about, setAbout] = useState(false);

  const status = useQuery({ queryKey: ["source-status", repoId], queryFn: () => api.sourceStatus(repoId), refetchOnMount: "always", refetchOnWindowFocus: true });
  const rev = useQuery({ queryKey: ["static-review", repoId], queryFn: () => api.reviewStatic(repoId), staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: false });
  const r = rev.data;
  const changed = status.data?.count ?? 0;

  const download = async (fmt: "markdown" | "sarif" | "json") => {
    try {
      const res = await fetch(`${API_URL}/repositories/${repoId}/review/export?fmt=${fmt}`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = fmt === "markdown" ? "code-review.md" : fmt === "sarif" ? "code-review.sarif" : "code-review.json";
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
    } catch (e) { toast.error((e as Error).message); }
  };

  const syncAndRun = async () => {
    setSyncing(true);
    const t = toast.loading("Syncing your latest files and re-indexing…");
    try { await api.refreshRepo(repoId); invalidate(repoId); await qc.invalidateQueries({ queryKey: ["source-status", repoId] }); await rev.refetch(); toast.success("Synced. The review below reflects your current files", { id: t }); }
    catch (e) { toast.error((e as Error).message, { id: t }); } finally { setSyncing(false); }
  };

  const base = r?.findings ?? [];
  const shown = useMemo(() => base.filter((f) => sev.has(f.severity) && (cat === "all" || f.category === cat) && (quiet || !QUIET.has(f.category) || cat !== "all") && (!q || `${f.file} ${f.message} ${f.rule}`.toLowerCase().includes(q.toLowerCase()))), [base, sev, cat, quiet, q]);
  const quietCount = base.filter((f) => QUIET.has(f.category)).length;
  const byFile = useMemo(() => { const m = new Map<string, StaticFinding[]>(); for (const f of shown) m.set(f.file, [...(m.get(f.file) ?? []), f]); return [...m.entries()]; }, [shown]);
  const serious = (r?.summary.by_severity.high ?? 0) + (r?.summary.by_severity.medium ?? 0);

  const aiMsg = useMemo(() => [...messages].reverse().find((m) => m.role === "assistant" && m.mode === "review"), [messages]);
  const aiRun = runs.find((x) => x.id === aiMsg?.runId);
  const aiBusy = runs.some((x) => x.state === "running");
  const ai = (aiMsg?.findings ?? aiMsg?.result?.findings ?? []).filter((f) => f.source === "ai");

  return (
    <div className="mx-auto max-w-[1100px] space-y-4 p-4 sm:p-6">
      <Tabs value={tab} onValueChange={setTab}>
      <PageHeader title="Code Review" icon={<ScanSearch />}
        description="Every analysable file is checked with real parsers and fixed rules: syntax in all supported languages, undefined names and typos (with “did you mean”), wrong imports, wrong call arguments, bug patterns and security. No model, no sampling, no guessing."
        actions={<Button onClick={() => rev.refetch()} loading={rev.isFetching} variant="outline"><RefreshCw />Re-run review</Button>} />
      <TabsList className="mb-4 border-b"><TabsTrigger value="project">Whole project</TabsTrigger><TabsTrigger value="paste">Paste code</TabsTrigger></TabsList>
      <TabsContent value="paste"><PasteReview /></TabsContent>
      <TabsContent value="project" className="space-y-4">

      {changed > 0 && (
        <div role="alert" className="flex flex-wrap items-start gap-3 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          <div className="min-w-0 flex-1 text-[13px]"><div className="font-medium">{changed} file{changed === 1 ? "" : "s"} changed in your original folder since this project was imported</div>
            <p className="mt-0.5 text-xs text-muted-foreground">The review reads the server’s copy of your project, so edits you made elsewhere are not included yet: {status.data!.changed.slice(0, 6).map((c) => `${c.file} (${c.change})`).join(", ")}{changed > 6 ? "…" : ""}</p></div>
          <Button size="sm" onClick={() => void syncAndRun()} loading={syncing}><FolderSync />Sync & review again</Button>
        </div>
      )}
      {changed === 0 && status.data && status.data.kind === "local" && <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><CircleCheck className="size-3.5 text-success" />The project copy matches your folder <span className="font-mono">{status.data.source}</span>.</p>}
      {status.data?.kind === "upload" && <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Info className="size-3.5" />{status.data.note}</p>}

      {rev.isLoading || (rev.isFetching && !r) ? (
        <Card><CardBody className="space-y-3" role="status" aria-live="polite"><div className="flex items-center gap-2 text-[13px]"><Loader2 className="size-4 animate-spin text-primary" />Analysing every file…</div><Skeleton className="h-24" /></CardBody></Card>
      ) : rev.isError ? <ErrorState title="The review could not run" error={rev.error} onRetry={() => rev.refetch()} /> : r && (
        <>
          <Card>
            <CardBody className="space-y-4">
              <div className={cn("flex items-start gap-3 rounded-lg px-3 py-2.5", serious ? "bg-destructive/8" : "bg-success/8")}>
                {serious ? <AlertTriangle className="mt-0.5 size-5 text-destructive" /> : <ShieldCheck className="mt-0.5 size-5 text-success" />}
                <div className="min-w-0"><div className="text-[13px] font-semibold">{serious ? `${serious} problem${serious === 1 ? "" : "s"} found that can crash or misbehave` : r.summary.total ? "No errors found, only low-priority notes" : `No problems found in ${r.coverage.files_analysed} files`}</div>
                  <p className="mt-0.5 text-xs text-muted-foreground">A clean result is only a statement about what was analysed. See “What was analysed” for exactly what that covers and what it cannot see.</p></div>
              </div>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
                <Stat label="Files analysed" value={r.coverage.files_analysed} hint={r.coverage.skipped.length ? `${r.coverage.skipped.length} skipped` : undefined} />
                <Stat label="High" value={r.summary.by_severity.high ?? 0} tone={r.summary.by_severity.high ? "destructive" : undefined} />
                <Stat label="Medium" value={r.summary.by_severity.medium ?? 0} tone={r.summary.by_severity.medium ? "warning" : undefined} />
                <Stat label="Low" value={r.summary.by_severity.low ?? 0} />
                <Stat label="Took" value={fmtMs(r.duration_ms)} hint={`${r.scope} scope`} />
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Button size="xs" variant="ghost" onClick={() => setAbout(!about)}><Info />What was analysed</Button>
                <Button size="xs" variant="ghost" onClick={async () => { await navigator.clipboard.writeText(toMarkdown(r, r.project.name)); toast.success("Report copied as Markdown"); }}><Clipboard />Copy report</Button>
                <Dropdown><DropdownTrigger asChild><Button size="xs" variant="ghost"><Download />Export report</Button></DropdownTrigger>
                  <DropdownContent align="start"><DropdownItem onSelect={() => void download("markdown")}>Markdown (.md)</DropdownItem><DropdownItem onSelect={() => void download("sarif")}>SARIF (GitHub code scanning)</DropdownItem><DropdownItem onSelect={() => void download("json")}>JSON</DropdownItem></DropdownContent></Dropdown>
                <span>Reviewed {ago(Date.now() / 1000)} · project indexed {ago(r.project.indexed_at)}</span>
              </div>
              {about && (
                <div className="space-y-3 rounded-lg border bg-surface/50 p-3 text-xs">
                  <div><div className="mb-1 font-medium">Checks by language</div><ul className="space-y-1.5">{r.coverage.languages.map((l) => <li key={l.language}><span className="font-medium capitalize">{l.language}</span> <span className="text-muted-foreground">· {l.files} file{l.files === 1 ? "" : "s"} · {l.findings} finding{l.findings === 1 ? "" : "s"}</span><div className="text-muted-foreground">{l.depth}</div></li>)}</ul></div>
                  <div><div className="mb-1 font-medium">What this cannot see</div><ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">{r.limits.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
                  {r.coverage.skipped.length > 0 && <div><div className="mb-1 font-medium">Skipped files</div><ul className="space-y-0.5 text-muted-foreground">{r.coverage.skipped.slice(0, 12).map((s) => <li key={s.file}><span className="font-mono">{s.file}</span>: {s.reason}</li>)}{r.coverage.skipped.length > 12 && <li>…and {r.coverage.skipped.length - 12} more</li>}</ul></div>}
                  {r.coverage.not_analysed_types.length > 0 && <div className="text-muted-foreground">File types without a checker: {r.coverage.not_analysed_types.join(", ")}</div>}
                </div>
              )}
            </CardBody>
          </Card>

          {base.length > 0 && (
            <Card>
              <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
                <div className="flex gap-1.5">{["high", "medium", "low"].map((s) => <button key={s} aria-pressed={sev.has(s)} onClick={() => setSev((c) => { const n = new Set(c); if (n.has(s)) n.delete(s); else n.add(s); return n; })} className={cn("rounded-md border px-2 py-0.5 text-xs capitalize", sev.has(s) ? "bg-accent font-medium" : "text-muted-foreground line-through")}>{s}</button>)}</div>
                <select aria-label="Category" value={cat} onChange={(e) => setCat(e.target.value)} className="h-7 rounded-md border bg-panel px-2 text-xs"><option value="all">All categories</option>{Object.entries(r.summary.by_category).map(([c, n]) => <option key={c} value={c}>{CATS[c]?.label ?? c} ({n})</option>)}</select>
                {quietCount > 0 && <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><input type="checkbox" checked={quiet} onChange={(e) => setQuiet(e.target.checked)} className="accent-[hsl(var(--primary))]" />Include unused-code & style notes ({quietCount})</label>}
                <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by file, message or rule…" aria-label="Filter findings" className="ml-auto h-7 w-56" />
                <span className="text-xs tabular-nums text-muted-foreground">{shown.length} shown</span>
              </div>
              {shown.length === 0 ? <p className="px-4 py-8 text-center text-xs text-muted-foreground">Nothing matches these filters.</p> : byFile.map(([file, items], i) => (
                <details key={file} open={i < 3 || items.some((x) => x.severity === "high")} className="group border-b last:border-0">
                  <summary className="flex cursor-pointer list-none items-center gap-2 bg-muted/40 px-4 py-2 text-[13px] hover:bg-muted/70"><ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-0 [details:not([open])_&]:-rotate-90" /><FileCode2 className="size-4 text-muted-foreground" /><span className="min-w-0 flex-1 truncate font-mono font-medium">{file}</span>
                    {items.filter((x) => x.severity === "high").length > 0 && <Badge variant="destructive">{items.filter((x) => x.severity === "high").length} high</Badge>}<Badge variant="outline">{items.length}</Badge></summary>
                  <ul>{items.map((f, k) => <Item key={f.id + k} f={f} defaultOpen={i === 0 && k === 0} />)}</ul>
                </details>
              ))}
            </Card>
          )}
        </>
      )}

      <Card>
        <CardHeader title="AI deep review (optional)" description="Static analysis cannot judge logic that is syntactically valid but wrong. A configured model can read the code for that." icon={<Sparkles className="size-4" />}
          actions={<Button size="sm" variant="outline" disabled={aiBusy || health.data?.llm_provider === "mock"} loading={aiBusy} onClick={() => void run("review", "Review this project for bugs, security problems and maintainability.")}><Play />Run AI review</Button>} />
        <CardBody className="space-y-2">
          {health.data?.llm_provider === "mock" && <MockNotice llm="mock" />}
          {aiBusy && <div className="flex items-center gap-2 text-xs text-muted-foreground" role="status" aria-live="polite"><Loader2 className="size-3.5 shrink-0 animate-spin" /><span className="min-w-0 flex-1 truncate">{currentActivity(runs.find((x) => x.state === "running"))}</span><Button size="xs" variant="ghost" onClick={stop}>Stop</Button></div>}
          {aiMsg?.state === "error" && <ErrorState error={aiMsg.error} />}
          {aiMsg?.state === "done" && (<>
            <MockNotice llm={aiMsg.result?.llm} />
            {aiMsg.result?.answer && <p className="text-[13px] leading-relaxed">{aiMsg.result.answer}</p>}
            {ai.length === 0 ? <p className="text-xs text-muted-foreground">The model reported no additional findings beyond the static analysis above.</p> : <ul className="divide-y rounded-lg border">{ai.map((f, i) => <li key={i} className="flex items-start gap-2.5 px-3 py-2 text-[13px]"><SeverityBadge s={f.severity} /><span className="min-w-0 flex-1"><FileLink path={f.file} line={f.line} /><span className="block text-xs text-muted-foreground">{f.message}</span>{f.grounded === false && <span className="text-[11px] text-warning">points at code that was not found at that location</span>}</span></li>)}</ul>}
          </>)}
          {!aiMsg && !aiBusy && health.data?.llm_provider !== "mock" && <p className="text-xs text-muted-foreground">Not run yet. Its findings are labelled AI and checked against the real code; the strict review above never depends on it.</p>}
          {aiRun && null}
        </CardBody>
      </Card>
      </TabsContent>
      </Tabs>
    </div>
  );
}
