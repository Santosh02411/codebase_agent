"use client";
import { useMemo, useRef, useState } from "react";
import { DiffEditor } from "@monaco-editor/react";
import type { editor as MonacoNS } from "monaco-editor";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, CheckCheck, FilePlus2, GitPullRequest, Play, Undo2, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { applyEdits, counts, editKey, filesOf, lineOf, newKey } from "@/lib/edits";
import { languageOf } from "@/lib/languages";
import type { Decision, Edit, Proposal, TestRun } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useApplyChanges, useFile, useGitVersions, useHealth, useRepos } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { FileIcon } from "./Explorer";

const DIFF_OPTS: MonacoNS.IDiffEditorConstructionOptions = {
  readOnly: true, originalEditable: false, renderSideBySide: true, automaticLayout: true, fontSize: 12.5, scrollBeyondLastLine: false,
  fontFamily: "JetBrains Mono, ui-monospace, Menlo, Consolas, monospace", minimap: { enabled: false }, padding: { top: 8 }, renderOverviewRuler: true,
};

export function TestPill({ t, label }: { t?: TestRun | null; label: string }) {
  if (!t) return <span className="text-muted-foreground">{label}: not run</span>;
  const v = t.passed ? "success" : t.status === "no_tests" ? "secondary" : "destructive";
  return <span className="inline-flex items-center gap-1.5 text-muted-foreground">{label}<Badge variant={v}>{t.status.replace("_", " ")}</Badge></span>;
}

function MiniDiff({ edit }: { edit: Edit }) {
  const cut = (t: string) => { const l = t.split("\n"); return l.length > 8 ? [...l.slice(0, 8), `… ${l.length - 8} more lines`] : l; };
  return (
    <pre className="mt-1 overflow-x-auto rounded bg-background/60 p-1.5 font-mono text-[10.5px] leading-snug">
      {cut(edit.search).map((l, i) => <div key={`s${i}`} className="bg-red-500/10 text-red-300">- {l}</div>)}
      {cut(edit.replace).map((l, i) => <div key={`r${i}`} className="bg-emerald-500/10 text-emerald-300">+ {l}</div>)}
    </pre>
  );
}

function DecisionButtons({ value, onChange }: { value: Decision; onChange: (d: Decision) => void }) {
  return (
    <div className="flex gap-1">
      <Button size="xs" variant={value === "accepted" ? "success" : "outline"} onClick={() => onChange(value === "accepted" ? "pending" : "accepted")}><Check /> Approve</Button>
      <Button size="xs" variant={value === "rejected" ? "destructive" : "outline"} onClick={() => onChange(value === "rejected" ? "pending" : "rejected")}><X /> Reject</Button>
    </div>
  );
}

/** Approve / reject each change of an AI proposal and see the exact result in a diff editor before anything is applied. */
export function ReviewTab({ repoId, proposalId }: { repoId: string; proposalId: string }) {
  const p = useIde((s) => s.proposals[proposalId]);
  const { setDecision, setAllDecisions, patchProposal, closeTab, setBottom, setSidebar } = useIde.getState();
  const files = useMemo(() => (p ? filesOf(p) : []), [p]);
  const [selected, setSelected] = useState<string | undefined>(files[0]);
  const current = selected && files.includes(selected) ? selected : files[0];
  const isNew = !!p?.newFiles.some((n) => n.path === current);
  const original = useFile(repoId, current && !isNew ? current : undefined);
  const apply = useApplyChanges(repoId);
  const diffRef = useRef<MonacoNS.IStandaloneDiffEditor | null>(null);
  const qc = useQueryClient();
  const health = useHealth();
  const repos = useRepos();
  const source = repos.data?.find((r) => r.id === repoId)?.source ?? "";
  const canPr = !!health.data?.github_configured && source.startsWith("https://github.com/");

  const fileEdits = useMemo(() => (p && current ? p.edits.map((e, i) => ({ e, i })).filter((x) => x.e.file === current) : []), [p, current]);
  const preview = useMemo(() => {
    if (!p || !current) return { text: "", conflicts: new Set<number>() };
    if (isNew) return { text: p.newFiles.find((n) => n.path === current)?.content ?? "", conflicts: new Set<number>() };
    const live = fileEdits.filter((x) => p.decisions[editKey(x.i)] !== "rejected");
    const r = applyEdits(original.data?.text ?? "", live.map((x) => x.e));
    return { text: r.text, conflicts: new Set(r.conflicts.map((c) => live[c].i)) };
  }, [p, current, isNew, fileEdits, original.data]);

  const pr = useMutation({
    mutationFn: async () => {
      if (!p) throw new Error("no proposal");
      const out: Record<string, string> = {};
      for (const f of files) {
        const nf = p.newFiles.find((n) => n.path === f);
        if (nf) { if (p.decisions[newKey(f)] === "accepted") out[f] = nf.content; continue; }
        const mine = p.edits.map((e, i) => ({ e, i })).filter((x) => x.e.file === f && p.decisions[editKey(x.i)] === "accepted");
        if (!mine.length) continue;
        const base = await qc.fetchQuery({ queryKey: ["file", repoId, f], queryFn: () => api.file(repoId, f), staleTime: 0 });
        out[f] = p.applied ? base.text : applyEdits(base.text, mine.map((x) => x.e)).text;
      }
      if (!Object.keys(out).length) throw new Error("Approve at least one change first");
      return api.createPr(repoId, out, p.title.slice(0, 70) || "AI change", `${p.explanation}\n\n_Generated with Codebase Agent._`);
    },
    onSuccess: (r) => { toast.success(`Pull request #${r.number} opened`, { action: { label: "Open", onClick: () => window.open(r.url, "_blank") } }); },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!p) return <div className="p-6 text-muted-foreground">This proposal is no longer available.</div>;
  const c = counts(p);
  const locked = p.applied || p.discarded;

  const onApply = () => {
    const edits = p.edits.filter((_, i) => p.decisions[editKey(i)] === "accepted");
    const newFiles = p.newFiles.filter((n) => p.decisions[newKey(n.path)] === "accepted");
    const touched = new Set([...edits.map((e) => e.file), ...newFiles.map((n) => n.path)]);
    const dirty = [...touched].filter((f) => useIde.getState().buffers[f] !== undefined);
    if (dirty.length && !confirm(`You have unsaved edits in ${dirty.join(", ")}. Applying will replace them. Continue?`)) return;
    apply.mutate({ edits, newFiles }, {
      onSuccess: (r) => {
        dirty.forEach((f) => useIde.getState().setBuffer(f, null));
        patchProposal(p.id, { applied: true });
        toast.success(`Applied ${r.files.length} file${r.files.length === 1 ? "" : "s"} to the project copy`);
        setSidebar("git");
      },
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-3 py-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{p.title}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-3 text-[11px]">
            <span className="text-muted-foreground">{c.total} change{c.total === 1 ? "" : "s"} in {files.length} file{files.length === 1 ? "" : "s"}</span>
            <TestPill t={p.testBefore} label="Tests before" /><TestPill t={p.testAfter} label="after" />
            {p.status && <Badge variant={p.status.includes("verified") ? "success" : p.status.includes("fail") ? "destructive" : "secondary"}>{p.status.replace("_", " ")}</Badge>}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {p.applied && <Badge variant="success">Applied to project copy</Badge>}
          {p.discarded && <Badge variant="secondary">Discarded</Badge>}
          {!locked && (
            <>
              <Button size="sm" variant="outline" onClick={() => setAllDecisions(p.id, "accepted")}><CheckCheck /> Approve all</Button>
              <Button size="sm" variant="outline" onClick={() => setAllDecisions(p.id, "rejected")}><X /> Reject all</Button>
              <Button size="sm" disabled={!c.accepted || apply.isPending} onClick={onApply}><Check /> {apply.isPending ? "Applying…" : `Apply ${c.accepted} approved`}</Button>
            </>
          )}
          {p.applied && <Button size="sm" variant="outline" onClick={() => { setBottom("tests"); void api.runTests(repoId).then((t) => useIde.getState().addTest("After applying change", t)).catch((e: Error) => toast.error(e.message)); }}><Play /> Run tests</Button>}
          {canPr && c.accepted > 0 && <Button size="sm" variant="secondary" disabled={pr.isPending} onClick={() => confirm("This creates a branch and a pull request on GitHub. Continue?") && pr.mutate()}><GitPullRequest /> {pr.isPending ? "Opening…" : "Open pull request"}</Button>}
          {!locked && <Button size="sm" variant="ghost" onClick={() => { patchProposal(p.id, { discarded: true }); closeTab(`review:${p.id}`); }}><Undo2 /> Discard</Button>}
        </div>
      </div>
      {p.explanation && <div className="border-b bg-muted/30 px-3 py-2 text-[12px] text-muted-foreground">{p.explanation}</div>}
      <div className="flex min-h-0 flex-1">
        <ScrollArea className="w-72 shrink-0 border-r">
          {files.map((f) => {
            const nf = p.newFiles.find((n) => n.path === f);
            const mine = p.edits.map((e, i) => ({ e, i })).filter((x) => x.e.file === f);
            return (
              <div key={f} className={cn("border-b", current === f && "bg-accent/40")}>
                <button className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left font-medium" onClick={() => setSelected(f)}>
                  {nf ? <FilePlus2 className="size-3.5 text-emerald-400" /> : <FileIcon name={f} />}<span className="truncate">{f}</span>{nf && <Badge variant="success" className="ml-auto">new</Badge>}
                </button>
                {nf && (
                  <div className="flex items-center justify-between gap-2 px-3 pb-2">
                    <span className="text-[11px] text-muted-foreground">{nf.content.split("\n").length} lines</span>
                    <DecisionButtons value={p.decisions[newKey(f)] ?? "pending"} onChange={(d) => !locked && setDecision(p.id, newKey(f), d)} />
                  </div>
                )}
                {mine.map(({ e, i }, n) => {
                  const d = p.decisions[editKey(i)] ?? "pending";
                  const needle = e.search.split("\n")[0];
                  return (
                    <div key={i} className="mx-2 mb-2 rounded-md border bg-panel p-2">
                      <div className="flex items-center gap-2">
                        <button className="font-medium hover:underline" onClick={() => { setSelected(f); window.setTimeout(() => diffRef.current?.getModifiedEditor().revealLineInCenter(lineOf(preview.text, e.replace.split("\n").find((l) => l.trim()) ?? needle)), 50); }}>
                          Change {n + 1} · line {original.data && current === f ? lineOf(original.data.text, e.search) : "…"}
                        </button>
                        {d !== "pending" && <Badge variant={d === "accepted" ? "success" : "destructive"}>{d}</Badge>}
                        {current === f && preview.conflicts.has(i) && <Badge variant="warning"><AlertTriangle className="size-3" /> won’t apply</Badge>}
                      </div>
                      <MiniDiff edit={e} />
                      {!locked && <div className="mt-2"><DecisionButtons value={d} onChange={(v) => setDecision(p.id, editKey(i), v)} /></div>}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </ScrollArea>
        <div className="min-w-0 flex-1">
          {current && (
            <DiffEditor
              key={current}
              height="100%"
              theme="vs-dark"
              language={languageOf(current)}
              original={isNew ? "" : original.data?.text ?? ""}
              modified={preview.text}
              options={DIFF_OPTS}
              onMount={(ed) => { diffRef.current = ed; }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

/** Working-copy changes vs. the imported version (opened from the Git panel). */
export function GitDiffTab({ repoId, path }: { repoId: string; path: string }) {
  const v = useGitVersions(repoId, path);
  const openFile = useIde((s) => s.openFile);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b px-3 py-1.5">
        <FileIcon name={path} /><span className="font-medium">{path}</span>
        {v.data?.is_new && <Badge variant="success">new</Badge>}{v.data?.is_deleted && <Badge variant="destructive">deleted</Badge>}
        <span className="text-muted-foreground">imported version ↔ working copy</span>
        <Button size="xs" variant="ghost" className="ml-auto" onClick={() => openFile(path)}>Open file</Button>
      </div>
      <div className="min-h-0 flex-1">
        {v.error ? <div className="p-4 text-destructive">{(v.error as Error).message}</div> : (
          <DiffEditor key={path} height="100%" theme="vs-dark" language={languageOf(path)} original={v.data?.original ?? ""} modified={v.data?.modified ?? ""} options={DIFF_OPTS} />
        )}
      </div>
    </div>
  );
}
