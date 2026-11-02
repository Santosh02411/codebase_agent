"use client";
import { useState } from "react";
import { Boxes, Braces, ChevronDown, ChevronRight, Database, FileCode2, GitBranch, GitCommitHorizontal, Network, Package, RefreshCw, Route, TestTube2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { useBranches, useCheckout, useCommits, useFetchHistory, useReindex, useStats } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import type { RepoStats } from "@/lib/types";
import { cn, fmtMs } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ProgressBar, ReportLine } from "./IndexProgress";

const LANG_COLOR: Record<string, string> = {
  python: "#3572A5", javascript: "#f1e05a", typescript: "#3178c6", java: "#b07219", go: "#00ADD8", rust: "#dea584", c: "#8f8f8f", cpp: "#f34b7d",
  markdown: "#083fa1", json: "#9a9a9a", yaml: "#cb171e", toml: "#9c4221", html: "#e34c26", css: "#563d7c", sql: "#e38c00", shell: "#89e051", text: "#666",
};

function Stat({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="rounded-lg border bg-background p-2.5">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground [&_svg]:size-3.5">{icon}{label}</div>
      <div className="mt-1 text-lg font-semibold leading-none">{value}</div>
      {sub && <div className="mt-1 truncate text-[10.5px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

function Section({ title, count, children, defaultOpen = false }: { title: string; count?: number | string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-1.5 px-3 py-2 text-left font-medium hover:bg-accent/40">
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}{title}{count !== undefined && <Badge variant="secondary" className="ml-auto">{count}</Badge>}
      </button>
      {open && <div className="pb-2">{children}</div>}
    </div>
  );
}

function Languages({ langs }: { langs: RepoStats["languages"] }) {
  const total = langs.reduce((n, l) => n + l.lines, 0) || 1;
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded">{langs.map((l) => <div key={l.language} title={`${l.language}: ${l.lines} lines`} style={{ width: `${(l.lines / total) * 100}%`, background: LANG_COLOR[l.language] ?? "#555" }} />)}</div>
      <div className="mt-2 grid grid-cols-[auto_1fr_auto_auto] items-center gap-x-2 gap-y-1 text-[11.5px]">
        {langs.slice(0, 8).map((l) => (
          <div key={l.language} className="contents">
            <span className="size-2 rounded-full" style={{ background: LANG_COLOR[l.language] ?? "#555" }} />
            <span>{l.language}</span><span className="text-right text-muted-foreground">{l.files} files</span><span className="w-12 text-right">{Math.round((l.lines / total) * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RepoPanel({ repoId }: { repoId: string }) {
  const stats = useStats(repoId);
  const branches = useBranches(repoId);
  const [commitLimit, setCommitLimit] = useState(15);
  const branch = branches.data?.current;
  const commits = useCommits(repoId, undefined, commitLimit);
  const checkout = useCheckout(repoId);
  const fetchMore = useFetchHistory(repoId);
  const reindex = useReindex();
  const { openFile, openGraph } = useIde.getState();
  const [target, setTarget] = useState("");

  const doCheckout = (ref: string) =>
    checkout.mutate({ ref }, {
      onError: (e) => {
        if (e instanceof ApiError && e.status === 409) {
          if (confirm(`${e.message}\n\nSwitch anyway and DISCARD those changes in the project copy?`)) checkout.mutate({ ref, force: true }, { onError: (e2) => toast.error(e2.message) });
        } else toast.error(e.message);
      },
    });

  const st = stats.data;
  const busy = checkout.isPending || reindex.isPending || st?.indexing.state === "indexing";
  const selected = target || branch || "";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center px-3 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span>Repository</span>
        <button className="ml-auto rounded p-1 hover:bg-accent" title="Re-index (only changed files are reprocessed)" disabled={busy} onClick={() => reindex.mutate(repoId)}><RefreshCw className={cn("size-3", busy && "animate-spin")} /></button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {stats.isLoading && <div className="px-3 py-2 text-muted-foreground">Loading statistics…</div>}
        {stats.error && <div className="px-3 py-2 text-destructive">{(stats.error as Error).message}</div>}
        {st && (
          <div className="space-y-3 px-3 pb-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold">{st.repo.name}{st.repo.provider && <Badge variant="outline">{st.repo.provider}</Badge>}</div>
              <div className="truncate text-[11px] text-muted-foreground" title={st.repo.source}>{st.repo.source}</div>
            </div>

            <div className="space-y-1.5 rounded-lg border bg-background p-2.5">
              {busy && st.indexing.state === "indexing" ? <ProgressBar status={st.indexing} /> : (
                <div className="flex items-center gap-2"><span className={cn("size-2 rounded-full", st.indexing.state === "error" ? "bg-destructive" : "bg-success")} /><span>{st.indexing.state === "error" ? "Indexing failed" : "Indexed"}</span>
                  <span className="ml-auto text-[11px] text-muted-foreground">{st.indexing.chunks} chunks · {st.indexing.embedder}</span></div>
              )}
              {st.indexing.state === "error" && <div className="text-[11px] text-destructive">{st.indexing.error}</div>}
              <ReportLine r={st.indexing.last_index} />
              {st.indexing.last_index?.changed_files?.length > 0 && st.indexing.last_index.mode === "incremental" && (
                <div className="flex flex-wrap gap-1 pt-0.5">{st.indexing.last_index.changed_files.slice(0, 6).map((f) => <button key={f} onClick={() => openFile(f)} className="rounded border px-1 font-mono text-[10px] text-muted-foreground hover:text-foreground">{f.split("/").pop()}</button>)}</div>
              )}
            </div>

            <div className="space-y-1.5 rounded-lg border bg-background p-2.5">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><GitBranch className="size-3.5" />Analyzing {st.repo.detached ? "commit" : "branch"}
                <b className="text-foreground">{st.repo.detached ? st.repo.commit : st.repo.branch}</b>{!st.repo.detached && st.repo.commit && <span>@ {st.repo.commit}</span>}</div>
              <div className="flex gap-1.5">
                <select value={selected} disabled={busy} onChange={(e) => setTarget(e.target.value)} className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-xs">
                  {branch === "" && <option value="">(detached HEAD)</option>}
                  {branches.data?.branches.map((b) => <option key={b.name} value={b.name}>{b.name}{b.remote ? "  · remote" : ""}{b.name === branches.data?.default ? "  · default" : ""}</option>)}
                </select>
                <Button size="sm" disabled={busy || !target || target === branch} onClick={() => { doCheckout(target); setTarget(""); }}>Switch</Button>
              </div>
              {branches.data?.shallow && <div className="text-[10.5px] text-muted-foreground">Shallow clone: only the latest commit of each branch is loaded. Use “Load more history” below for older commits.</div>}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <Stat icon={<FileCode2 />} label="Files" value={st.files.toLocaleString()} sub={`${st.lines.toLocaleString()} lines · ${st.code_files} code`} />
              <Stat icon={<Braces />} label="Functions" value={(st.symbols.functions + st.symbols.methods).toLocaleString()} sub={`${st.symbols.functions} funcs · ${st.symbols.methods} methods`} />
              <Stat icon={<Boxes />} label="Classes & types" value={(st.symbols.classes + st.symbols.interfaces + st.symbols.structs + st.symbols.enums).toLocaleString()} sub={`${st.symbols.classes} class · ${st.symbols.interfaces} iface/trait · ${st.symbols.structs} struct · ${st.symbols.enums} enum`} />
              <Stat icon={<Package />} label="Dependencies" value={st.dependencies.declared_count} sub={`${st.dependencies.external_imports.length} imported externally`} />
              <Stat icon={<TestTube2 />} label="Tests" value={st.tests.cases} sub={`${st.tests.files} test files`} />
              <Stat icon={<Route />} label="API endpoints" value={st.apis.count} sub={[...new Set(st.apis.items.map((a) => a.framework))].slice(0, 2).join(", ") || "none detected"} />
              <Stat icon={<Database />} label="DB models" value={st.models.length} sub={[...new Set(st.models.map((m) => m.framework))].slice(0, 2).join(", ") || "none detected"} />
              <Stat icon={<Network />} label="Call graph" value={`${st.graph.call_resolution_pct}%`} sub={`${st.graph.call_edges} edges · ${st.graph.module_edges} imports`} />
            </div>

            <div className="flex gap-1.5">
              <Button size="sm" variant="outline" className="flex-1" onClick={() => openGraph("modules", undefined, "Module graph")}><Network /> Module graph</Button>
            </div>
            <Languages langs={st.languages} />
          </div>
        )}

        {st && (
          <>
            <Section title="API endpoints" count={st.apis.count}>
              {st.apis.items.length === 0 && <div className="px-3 text-muted-foreground">No routes detected (Flask, FastAPI, Django, Express, NestJS, Spring, Go, Actix/Axum are supported).</div>}
              {st.apis.items.slice(0, 80).map((a, i) => (
                <button key={i} onClick={() => openFile(a.file, a.line)} className="flex w-full items-center gap-2 px-3 py-1 text-left hover:bg-accent/50">
                  <Badge variant={a.method === "GET" ? "success" : a.method === "DELETE" ? "destructive" : a.method === "ANY" ? "secondary" : "warning"} className="w-12 justify-center">{a.method.split("|")[0]}</Badge>
                  <span className="truncate font-mono text-[11px]">{a.path}</span><span className="ml-auto truncate text-[10.5px] text-muted-foreground">{a.file.split("/").pop()}:{a.line}</span>
                </button>
              ))}
            </Section>
            <Section title="Database models" count={st.models.length}>
              {st.models.map((m) => (
                <button key={`${m.file}:${m.name}`} onClick={() => openFile(m.file, m.line)} className="flex w-full items-center gap-2 px-3 py-1 text-left hover:bg-accent/50">
                  <Database className="size-3.5 text-violet-400" /><span className="truncate font-medium">{m.name}</span><Badge variant="outline">{m.framework || "orm"}</Badge><span className="ml-auto text-[10.5px] text-muted-foreground">{m.fields} fields</span>
                </button>
              ))}
              {st.models.length === 0 && <div className="px-3 text-muted-foreground">No ORM models detected.</div>}
            </Section>
            <Section title="Dependencies" count={st.dependencies.declared_count}>
              {st.dependencies.manifests.length > 0 && <div className="px-3 pb-1 text-[11px] text-muted-foreground">From {st.dependencies.manifests.join(", ")}</div>}
              <div className="flex flex-wrap gap-1 px-3">{st.dependencies.declared.slice(0, 120).map((d) => <Badge key={`${d.ecosystem}:${d.name}`} variant="secondary" title={d.ecosystem}>{d.name}</Badge>)}</div>
              {st.dependencies.external_imports.length > 0 && <div className="px-3 pt-2 text-[11px] font-medium text-muted-foreground">Imported by your code (files)</div>}
              <div className="flex flex-wrap gap-1 px-3 pt-1">{st.dependencies.external_imports.slice(0, 40).map((d) => <Badge key={d.name} variant="outline">{d.name} · {d.files}</Badge>)}</div>
            </Section>
            <Section title="Tests" count={`${st.tests.cases} in ${st.tests.files}`}>
              {st.tests.file_list.map((f) => <button key={f} onClick={() => openFile(f)} className="block w-full truncate px-3 py-1 text-left font-mono text-[11px] hover:bg-accent/50">{f}</button>)}
            </Section>
            <Section title="Commits" count={commits.data?.length ?? 0} defaultOpen>
              {commits.data?.map((c) => (
                <div key={c.sha} className="group flex items-start gap-2 px-3 py-1 hover:bg-accent/40">
                  <GitCommitHorizontal className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1"><div className="truncate">{c.subject}</div><div className="text-[10.5px] text-muted-foreground">{c.short} · {c.author} · {new Date(c.date).toLocaleDateString()}</div></div>
                  <button disabled={busy} onClick={() => doCheckout(c.sha)} className="hidden shrink-0 rounded border px-1.5 py-0.5 text-[10.5px] hover:bg-background group-hover:block" title="Analyze the code as of this commit">Analyze</button>
                </div>
              ))}
              <div className="flex gap-1.5 px-3 pt-1.5">
                <Button size="xs" variant="outline" onClick={() => setCommitLimit((n) => n + 30)}>Show more</Button>
                {branches.data?.shallow && <Button size="xs" variant="outline" disabled={fetchMore.isPending} onClick={() => fetchMore.mutate()}>Load more history</Button>}
              </div>
            </Section>
            {(st.parse_errors.length > 0 || Object.keys(st.parsers).length > 0) && (
              <Section title="Parsing" count={st.parse_errors.length ? `${st.parse_errors.length} issues` : "ok"}>
                <div className="flex flex-wrap gap-1 px-3">{Object.entries(st.parsers).map(([p, n]) => <Badge key={p} variant="outline">{p} · {n}</Badge>)}</div>
                {st.parse_errors.map((e) => <button key={e.file} onClick={() => openFile(e.file)} className="block w-full px-3 py-1 text-left hover:bg-accent/50"><span className="font-mono text-[11px]">{e.file}</span><span className="block text-[10.5px] text-warning">{e.errors[0]}</span></button>)}
              </Section>
            )}
            <div className="border-t px-3 py-2 text-[10.5px] text-muted-foreground">Last indexed {st.indexing.indexed_at ? new Date(st.indexing.indexed_at).toLocaleString() : "—"} · {fmtMs(st.indexing.last_index?.duration_ms)}</div>
          </>
        )}
      </ScrollArea>
    </div>
  );
}
