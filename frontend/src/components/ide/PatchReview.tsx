"use client";
import { useEffect, useMemo, useState } from "react";
import { DiffEditor } from "@monaco-editor/react";
import type { editor as MonacoNS } from "monaco-editor";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, CheckCheck, FilePlus2, RotateCcw, ShieldAlert, ShieldCheck, Trash2, Undo2, Wrench, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { languageOf } from "@/lib/languages";
import type { Decision, PatchChecks, PatchRecord, Verdict, VerdictStatus } from "@/lib/types";
import { cn, uid } from "@/lib/utils";
import { useInvalidateRepo } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { useMonacoTheme } from "@/lib/monacoTheme";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { FileIcon } from "./Explorer";
import { TestPill } from "./DiffViews";

const DIFF_OPTS: MonacoNS.IDiffEditorConstructionOptions = {
  readOnly: true, originalEditable: false, renderSideBySide: true, automaticLayout: true, fontSize: 12.5, scrollBeyondLastLine: false,
  fontFamily: "JetBrains Mono, ui-monospace, Menlo, Consolas, monospace", minimap: { enabled: false }, padding: { top: 8 }, renderOverviewRuler: true,
};

const VERDICT: Record<VerdictStatus, { v: "success" | "warning" | "destructive"; t: string }> = {
  resolved: { v: "success", t: "resolved" }, no_regressions: { v: "success", t: "no regressions" }, partial: { v: "warning", t: "partially resolved" },
  unverified: { v: "warning", t: "not verified" }, not_resolved: { v: "destructive", t: "not resolved" },
};

export function VerdictBadge({ v }: { v?: Verdict | null }) {
  if (!v) return null;
  const x = VERDICT[v.status];
  return <Badge variant={x.v} title={v.summary}>{x.t}</Badge>;
}

const OP_BADGE = { create: { v: "success", t: "new" }, delete: { v: "destructive", t: "deleted" }, modify: { v: "secondary", t: "modified" } } as const;

function ChecksPanel({ rec, onRecheck, onRevert, onRepair, busy }: { rec: PatchRecord; onRecheck: () => void; onRevert: () => void; onRepair: () => void; busy: string | null }) {
  const c: PatchChecks | null = rec.checks;
  if (!c) return <div className="border-t bg-muted/30 px-3 py-2 text-[12px] text-muted-foreground">Applied without running checks.</div>;
  const blocking = c.lint_new.filter((i) => i.blocking);
  const failed = c.status !== "passed";
  return (
    <div className={cn("border-t px-3 py-2.5 text-[12px]", c.status === "passed" ? "bg-emerald-500/5" : c.status === "failed" ? "bg-red-500/10" : "bg-amber-500/10")}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="flex items-center gap-1.5 font-semibold">
          {c.status === "passed" ? <ShieldCheck className="size-4 text-emerald-400" /> : <ShieldAlert className="size-4 text-red-400" />}
          Checks after applying: {c.status}
        </span>
        <VerdictBadge v={c.verdict} />
        <TestPill t={c.tests_before} label="Tests before" /><TestPill t={c.tests_after} label="after" />
        <span className="text-muted-foreground">Linter ({c.lint_after?.tool ?? "none"}): {c.lint_new.length === 0 ? "no new findings" : `${c.lint_new.length} new, ${blocking.length} blocking`}</span>
      </div>
      <div className="mt-1 text-muted-foreground">{c.verdict.summary}.</div>
      {c.tests_after?.failed_tests && c.tests_after.failed_tests.length > 0 && c.tests_after.status !== "passed" && (
        <ul className="mt-1.5 space-y-0.5 font-mono text-[11px]">{c.tests_after.failed_tests.slice(0, 5).map((t) => <li key={t.id} className="truncate text-red-300">✗ {t.id}{t.message ? ` — ${t.message}` : ""}</li>)}</ul>
      )}
      {blocking.slice(0, 4).map((i, n) => <div key={n} className="mt-0.5 truncate font-mono text-[11px] text-red-300">⚠ {i.file}:{i.line} {i.code} {i.message}</div>)}
      {failed && c.tests_after?.output && <pre className="mt-1.5 max-h-28 overflow-auto rounded bg-background/60 p-1.5 font-mono text-[10.5px]">{c.tests_after.output.slice(-1200)}</pre>}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {failed && rec.status === "applied" && <Button size="sm" disabled={busy !== null} onClick={onRepair}><Wrench /> {busy === "repair" ? "Analysing the failure…" : "Ask the agent to fix this"}</Button>}
        {rec.status === "applied" && <Button size="sm" variant="outline" disabled={busy !== null} onClick={onRecheck}><RotateCcw /> {busy === "recheck" ? "Running…" : "Re-run checks"}</Button>}
        {rec.status === "applied" && <Button size="sm" variant="ghost" disabled={busy !== null} onClick={onRevert}><Undo2 /> Revert patch</Button>}
      </div>
    </div>
  );
}

/** The exact diff of an agent (or hand-made) patch in Monaco's diff editor. Nothing is written until the user approves, and the checks run right after. */
export function PatchReviewTab({ repoId, patchId }: { repoId: string; patchId: string }) {
  const monacoTheme = useMonacoTheme();
  const qc = useQueryClient();
  const invalidate = useInvalidateRepo();
  const { closeTab, setSidebar, openPatch, addMessage } = useIde.getState();
  const provider = useIde((s) => s.provider);
  const rec = useQuery({ queryKey: ["patch", patchId], queryFn: () => api.patch(patchId) });
  const files = rec.data?.files ?? [];
  const [selected, setSelected] = useState<string | undefined>();
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const current = selected && files.some((f) => f.path === selected) ? selected : files[0]?.path;
  const versions = useQuery({ queryKey: ["patchfile", patchId, current], queryFn: () => api.patchFile(patchId, current!), enabled: !!current, staleTime: Infinity });
  useEffect(() => { setDecisions((d) => Object.fromEntries(files.map((f) => [f.path, d[f.path] ?? "pending"]))); }, [files.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const approved = useMemo(() => files.filter((f) => decisions[f.path] === "accepted"), [files, decisions]);
  const setPatch = (r: PatchRecord) => qc.setQueryData(["patch", patchId], r);

  const apply = useMutation({
    mutationFn: () => api.applyPatch(patchId, approved.length === files.length ? undefined : approved.map((f) => f.path), true),
    onSuccess: (r) => {
      setPatch(r); invalidate(repoId);
      for (const f of r.applied_files) useIde.getState().setBuffer(f, null);
      const ok = r.checks?.status === "passed";
      (ok ? toast.success : toast.warning)(ok ? `Applied ${r.applied_files.length} file(s); tests and linter passed` : "Applied, but the checks did not pass: see the panel below the diff");
      if (r.checks?.tests_after) useIde.getState().addTest("After applying patch", r.checks.tests_after);
      setSidebar("git");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const act = async (name: string, fn: () => Promise<PatchRecord>, done: string) => {
    setBusy(name);
    try { const r = await fn(); setPatch(r); invalidate(repoId); toast.success(done); } catch (e) { toast.error((e as Error).message); } finally { setBusy(null); }
  };
  const repair = async () => {
    setBusy("repair");
    try {
      const d = await api.repairPatch(patchId, provider);
      addMessage({ id: uid(), role: "assistant", mode: "debug", text: "", state: "done", result: d, sources: d.sources, ts: Date.now() });
      if (d.patch_id) { openPatch(d.patch_id, "correction"); toast.success("The agent proposed another correction"); } else toast.message("The agent could not propose a correction");
    } catch (e) { toast.error((e as Error).message); } finally { setBusy(null); }
  };

  if (rec.isLoading) return <div className="p-6 text-muted-foreground">Loading patch…</div>;
  if (rec.error || !rec.data) return <div className="p-6 text-destructive">{(rec.error as Error | null)?.message ?? "Patch not found"}</div>;
  const r = rec.data;
  const locked = r.status !== "proposed";
  const deletes = files.filter((f) => f.op === "delete" && decisions[f.path] === "accepted");
  const v = r.checks?.verdict ?? r.verification?.verdict;
  const onApply = () => {
    const dirty = approved.filter((f) => useIde.getState().buffers[f.path] !== undefined).map((f) => f.path);
    if (dirty.length && !confirm(`You have unsaved edits in ${dirty.join(", ")}. Applying will replace them. Continue?`)) return;
    if (deletes.length && !confirm(`This patch DELETES ${deletes.map((f) => f.path).join(", ")}. Continue?`)) return;
    apply.mutate();
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-3 py-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{r.title}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-3 text-[11px]">
            <span className="text-muted-foreground">{r.stats.files} file{r.stats.files === 1 ? "" : "s"} · <span className="text-emerald-400">+{r.stats.additions}</span> <span className="text-red-400">−{r.stats.deletions}</span></span>
            <Badge variant={r.status === "applied" ? "success" : r.status === "proposed" ? "outline" : "secondary"}>{r.status}</Badge>
            {v && <><span className="text-muted-foreground">{r.checks ? "after applying" : "verified by the agent"}:</span><VerdictBadge v={v} /></>}
            {r.verification?.test_before && <TestPill t={r.verification.test_before} label="Tests before" />}{r.verification?.test_after && <TestPill t={r.verification.test_after} label="after" />}
            {r.verification?.regression && <span className="text-muted-foreground">regression test {r.verification.regression.failed_before ? "reproduces the bug" : "does not reproduce the bug"}</span>}
            {r.parent_id && <button className="text-primary hover:underline" onClick={() => openPatch(r.parent_id!, "previous")}>correction of an earlier patch</button>}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {!locked && (
            <>
              <Button size="sm" variant="outline" onClick={() => setDecisions(Object.fromEntries(files.map((f) => [f.path, "accepted" as Decision])))}><CheckCheck /> Approve all</Button>
              <Button size="sm" variant="outline" onClick={() => setDecisions(Object.fromEntries(files.map((f) => [f.path, "rejected" as Decision])))}><X /> Reject all</Button>
              <Button size="sm" disabled={!approved.length || apply.isPending} onClick={onApply} title="Writes the approved files, then runs the tests and linter"><Check /> {apply.isPending ? "Applying & checking…" : `Apply ${approved.length} approved file${approved.length === 1 ? "" : "s"}`}</Button>
              <Button size="sm" variant="ghost" onClick={() => void act("reject", () => api.rejectPatch(patchId), "Patch rejected").then(() => closeTab(`patch:${patchId}`))}><Undo2 /> Reject patch</Button>
            </>
          )}
          {r.status === "applied" && <Badge variant="success">Applied to the project copy</Badge>}
          {r.status === "reverted" && <Badge variant="secondary">Reverted</Badge>}
        </div>
      </div>
      {r.explanation && <div className="border-b bg-muted/30 px-3 py-2 text-[12px] text-muted-foreground">{r.explanation}</div>}
      {!locked && <div className="flex items-center gap-1.5 border-b bg-amber-500/10 px-3 py-1 text-[11.5px] text-amber-200"><AlertTriangle className="size-3.5" />Nothing has been changed yet. Review the exact diff of each file, approve the files you want, then apply: tests and linter run automatically.</div>}
      <div className="flex min-h-0 flex-1">
        <ScrollArea className="w-72 shrink-0 border-r">
          {files.map((f) => {
            const d = decisions[f.path] ?? "pending";
            const ob = OP_BADGE[f.op];
            return (
              <div key={f.path} className={cn("border-b", current === f.path && "bg-accent/40")}>
                <button className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left font-medium" onClick={() => setSelected(f.path)}>
                  {f.op === "create" ? <FilePlus2 className="size-3.5 text-emerald-400" /> : f.op === "delete" ? <Trash2 className="size-3.5 text-red-400" /> : <FileIcon name={f.path} />}
                  <span className="truncate">{f.path}</span><Badge variant={ob.v} className="ml-auto">{ob.t}</Badge>
                </button>
                <div className="flex items-center justify-between gap-2 px-3 pb-2">
                  <span className="text-[11px]"><span className="text-emerald-400">+{f.additions}</span> <span className="text-red-400">−{f.deletions}</span>{f.fuzzy && <span className="ml-1.5 text-amber-300" title={f.notes.join("; ")}>whitespace-tolerant match</span>}</span>
                  {!locked && (
                    <div className="flex gap-1">
                      <Button size="xs" variant={d === "accepted" ? "success" : "outline"} onClick={() => setDecisions((x) => ({ ...x, [f.path]: d === "accepted" ? "pending" : "accepted" }))}><Check /> Approve</Button>
                      <Button size="xs" variant={d === "rejected" ? "destructive" : "outline"} onClick={() => setDecisions((x) => ({ ...x, [f.path]: d === "rejected" ? "pending" : "rejected" }))}><X /> Reject</Button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </ScrollArea>
        <div className="min-w-0 flex-1">
          {current && (versions.data ? (
            <DiffEditor key={`${current}:${r.status}`} height="100%" theme={monacoTheme} language={languageOf(current)} original={versions.data.original} modified={versions.data.modified} options={DIFF_OPTS} />
          ) : <div className="p-4 text-muted-foreground">{versions.error ? (versions.error as Error).message : "Loading diff…"}</div>)}
        </div>
      </div>
      {r.status === "applied" || r.checks ? <ChecksPanel rec={r} busy={busy} onRecheck={() => void act("recheck", () => api.recheckPatch(patchId), "Checks finished")}
        onRevert={() => confirm("Restore the files exactly as they were before this patch?") && void act("revert", () => api.revertPatch(patchId), "Patch reverted")} onRepair={() => void repair()} /> : null}
    </div>
  );
}
