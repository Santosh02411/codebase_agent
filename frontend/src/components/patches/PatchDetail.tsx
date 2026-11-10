"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { DiffEditor } from "@monaco-editor/react";
import type { editor as MonacoNS } from "monaco-editor";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, FilePlus2, History, RotateCcw, ShieldAlert, ShieldCheck, Trash2, Undo2, Wrench, X, FileCode2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useInvalidateRepo } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { languageOf } from "@/lib/languages";
import { useMonacoTheme } from "@/lib/monacoTheme";
import { cn, uid } from "@/lib/utils";
import type { Decision, PatchRecord } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import { ErrorState } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";
import { TestRunCard, VerdictBanner } from "@/components/chat/TestResult";

const DIFF_OPTS: MonacoNS.IDiffEditorConstructionOptions = { readOnly: true, originalEditable: false, renderSideBySide: true, automaticLayout: true, fontSize: 12.5, scrollBeyondLastLine: false,
  fontFamily: "JetBrains Mono, ui-monospace, Menlo, Consolas, monospace", minimap: { enabled: false }, padding: { top: 8 }, renderOverviewRuler: true };
const OP = { create: { v: "success", t: "new" }, delete: { v: "destructive", t: "deleted" }, modify: { v: "secondary", t: "modified" } } as const;

function Checks({ r, busy, onRecheck, onRevert, onRepair }: { r: PatchRecord; busy: string | null; onRecheck: () => void; onRevert: () => void; onRepair: () => void }) {
  const c = r.checks;
  if (!c) return <div className="rounded-lg border bg-secondary/40 px-3 py-2.5 text-xs text-muted-foreground">Applied without running checks.</div>;
  const blocking = c.lint_new.filter((i) => i.blocking);
  return (
    <div className="space-y-2.5 rounded-lg border bg-panel p-3">
      <div className="flex flex-wrap items-center gap-2 text-[13px] font-semibold">{c.status === "passed" ? <ShieldCheck className="size-4 text-success" /> : <ShieldAlert className="size-4 text-destructive" />}Checks after applying: <span className="capitalize">{c.status}</span></div>
      <VerdictBanner v={c.verdict} />
      <div className="grid gap-2 md:grid-cols-2"><TestRunCard title="Tests before" run={c.tests_before} /><TestRunCard title="Tests after" run={c.tests_after} /></div>
      <div className="text-xs text-muted-foreground">Linter ({c.lint_after?.tool ?? "none"}): {c.lint_new.length === 0 ? "no new findings" : `${c.lint_new.length} new, ${blocking.length} blocking`}</div>
      {blocking.slice(0, 4).map((i, n) => <div key={n} className="truncate rounded bg-destructive/8 px-2 py-1 font-mono text-[11px] text-destructive">{i.file}:{i.line} {i.code} {i.message}</div>)}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" loading={busy === "recheck"} onClick={onRecheck}><RotateCcw />Re-run checks</Button>
        {r.status === "applied" && <Button size="sm" variant="outline" loading={busy === "revert"} onClick={onRevert}><Undo2 />Revert</Button>}
        {c.status !== "passed" && <Button size="sm" loading={busy === "repair"} onClick={onRepair}><Wrench />Ask the agent for a correction</Button>}
      </div>
    </div>
  );
}

/** One patch in full: the exact per-file diff, per-file approval, apply (then checks run), reject, revert, re-check, agent repair. Nothing is written until the user approves. */
export function PatchDetail({ repoId, patchId, compact }: { repoId: string; patchId: string; compact?: boolean }) {
  const monacoTheme = useMonacoTheme();
  const qc = useQueryClient();
  const router = useRouter();
  const invalidate = useInvalidateRepo();
  const provider = useIde((s) => s.provider);
  const rec = useQuery({ queryKey: ["patch", patchId], queryFn: () => api.patch(patchId) });
  const files = rec.data?.files ?? [];
  const [selected, setSelected] = useState<string | undefined>();
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<null | "apply" | "revert" | "reject">(null);
  const current = selected && files.some((f) => f.path === selected) ? selected : files[0]?.path;
  const versions = useQuery({ queryKey: ["patchfile", patchId, current], queryFn: () => api.patchFile(patchId, current!), enabled: !!current, staleTime: Infinity });
  useEffect(() => { setDecisions((d) => Object.fromEntries(files.map((f) => [f.path, d[f.path] ?? "pending"]))); }, [files.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const approved = useMemo(() => files.filter((f) => decisions[f.path] === "accepted"), [files, decisions]);
  const setPatch = (r: PatchRecord) => { qc.setQueryData(["patch", patchId], r); qc.invalidateQueries({ queryKey: ["patches"] }); };

  const apply = useMutation({
    mutationFn: () => api.applyPatch(patchId, approved.length === files.length ? undefined : approved.map((f) => f.path), true),
    onSuccess: (r) => {
      setPatch(r); invalidate(repoId); setConfirm(null);
      for (const f of r.applied_files) useIde.getState().setBuffer(f, null);
      const ok = r.checks?.status === "passed";
      (ok ? toast.success : toast.warning)(ok ? `Applied ${r.applied_files.length} file(s); tests and linter passed` : "Applied, but the checks did not pass. See the checks below the diff.");
      if (r.checks?.tests_after) useIde.getState().addTest("After applying patch", r.checks.tests_after);
    },
    onError: (e: Error) => { setConfirm(null); toast.error(e.message); },
  });
  const act = async (name: string, fn: () => Promise<PatchRecord>, done: string) => {
    setBusy(name);
    try { const r = await fn(); setPatch(r); invalidate(repoId); toast.success(done); } catch (e) { toast.error((e as Error).message); } finally { setBusy(null); setConfirm(null); }
  };
  const repair = async () => {
    setBusy("repair");
    try {
      const d = await api.repairPatch(patchId, provider);
      useIde.getState().addMessage({ id: uid(), role: "assistant", mode: "debug", text: "", state: "done", result: d, sources: d.sources, patchId: d.patch_id ?? undefined, ts: Date.now() });
      if (d.patch_id) { toast.success("The agent proposed another correction"); router.push(`/changes?patch=${d.patch_id}`); } else toast.message("The agent could not propose a correction");
    } catch (e) { toast.error((e as Error).message); } finally { setBusy(null); }
  };

  if (rec.isLoading) return <div className="space-y-3 p-4"><Skeleton className="h-16" /><Skeleton className="h-72" /></div>;
  if (rec.error || !rec.data) return <div className="p-4"><ErrorState title="Patch not available" error={rec.error ?? "Patch not found"} onRetry={() => rec.refetch()} /></div>;
  const r = rec.data;
  const locked = r.status !== "proposed";
  const v = r.checks?.verdict ?? r.verification?.verdict ?? null;
  const unverified = !v || v.status === "unverified" || v.status === "not_resolved" || v.status === "partial";
  const deletes = approved.filter((f) => f.op === "delete");

  return (
    <div className={cn("space-y-3", compact ? "" : "p-4")}>
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1"><div className="truncate text-sm font-semibold">{r.title}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>{r.stats.files} file{r.stats.files === 1 ? "" : "s"}</span><span className="text-success">+{r.stats.additions}</span><span className="text-destructive">−{r.stats.deletions}</span>
            <Badge variant={r.status === "applied" ? "success" : r.status === "proposed" ? "warning" : "secondary"}>{r.status}</Badge>
            {r.parent_id && <button className="text-primary hover:underline" onClick={() => router.push(`/changes?patch=${r.parent_id}`)}>correction of an earlier patch</button>}</div></div>
        {!locked && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Button size="sm" variant="outline" onClick={() => setDecisions(Object.fromEntries(files.map((f) => [f.path, "accepted" as Decision])))}><CheckCheck />Approve all</Button>
            <Button size="sm" variant="outline" onClick={() => setDecisions(Object.fromEntries(files.map((f) => [f.path, "rejected" as Decision])))}><X />Reject all</Button>
            <Button size="sm" disabled={!approved.length} loading={apply.isPending} onClick={() => setConfirm("apply")}><Check />{unverified ? "Apply suggested fix" : "Apply verified fix"}{approved.length !== files.length ? ` (${approved.length})` : ""}</Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirm("reject")}><Undo2 />Reject</Button>
          </div>
        )}
      </div>
      <VerdictBanner v={v} />
      {r.explanation && <div className="rounded-lg bg-surface px-3 py-2.5 text-[13px] leading-relaxed text-muted-foreground">{r.explanation}</div>}
      {r.verification?.regression && <div className="flex items-center gap-2 text-xs"><Badge variant={r.verification.regression.failed_before && r.verification.regression.passed_after ? "success" : "warning"}>regression test</Badge><span className="text-muted-foreground">{r.verification.regression.failed_before ? "fails on the original code" : "does not fail on the original code"} · {r.verification.regression.passed_after ? "passes with the patch" : "does not pass with the patch"} ({r.verification.regression.tests.join(", ")})</span></div>}
      {(r.verification?.test_before || r.verification?.test_after) && !r.checks && <div className="grid gap-2 md:grid-cols-2"><TestRunCard title="Tests before the change" run={r.verification?.test_before} /><TestRunCard title="Tests with the change" run={r.verification?.test_after} /></div>}
      {!locked ? null : null}
      <div className="overflow-hidden rounded-xl border bg-panel">
        <div className="flex flex-col md:flex-row">
          <ul className="max-h-48 shrink-0 divide-y overflow-y-auto border-b md:max-h-[460px] md:w-72 md:border-b-0 md:border-r">
            {files.map((f) => {
              const d = decisions[f.path] ?? "pending";
              return (
                <li key={f.path} className={cn(current === f.path && "bg-accent/50")}>
                  <button className="flex w-full items-center gap-1.5 px-3 pt-2 text-left text-[13px] font-medium" onClick={() => setSelected(f.path)}>
                    {f.op === "create" ? <FilePlus2 className="size-3.5 text-success" /> : f.op === "delete" ? <Trash2 className="size-3.5 text-destructive" /> : <FileCode2 className="size-3.5 text-info" />}
                    <span className="truncate">{f.path}</span><Badge variant={OP[f.op].v} className="ml-auto">{OP[f.op].t}</Badge></button>
                  <div className="flex items-center justify-between gap-2 px-3 pb-2 pt-1 text-[11px]"><span><span className="text-success">+{f.additions}</span> <span className="text-destructive">−{f.deletions}</span>{f.fuzzy && <span className="ml-1.5 text-warning" title={f.notes.join("; ")}>whitespace-tolerant match</span>}</span>
                    {!locked && <span className="flex gap-1"><Button size="xs" variant={d === "accepted" ? "success" : "outline"} onClick={() => setDecisions((x) => ({ ...x, [f.path]: d === "accepted" ? "pending" : "accepted" }))} aria-pressed={d === "accepted"}><Check />Approve</Button><Button size="xs" variant={d === "rejected" ? "destructive" : "outline"} onClick={() => setDecisions((x) => ({ ...x, [f.path]: d === "rejected" ? "pending" : "rejected" }))} aria-pressed={d === "rejected"}><X />Skip</Button></span>}</div>
                </li>
              );
            })}
          </ul>
          <div className="h-[460px] min-w-0 flex-1">
            {current && (versions.data ? <DiffEditor key={`${current}:${r.status}`} height="100%" theme={monacoTheme} language={languageOf(current)} original={versions.data.original} modified={versions.data.modified} options={DIFF_OPTS} />
              : <div className="p-4 text-xs text-muted-foreground">{versions.error ? (versions.error as Error).message : "Loading diff…"}</div>)}
          </div>
        </div>
      </div>
      {!locked ? <p className="text-xs text-muted-foreground">Nothing has been changed in your project yet. Review each file’s diff, approve the files you want, then apply. Tests and the linter run automatically afterwards.</p> : null}
      {(r.status === "applied" || r.checks) && <Checks r={r} busy={busy} onRecheck={() => void act("recheck", () => api.recheckPatch(patchId), "Checks finished")} onRevert={() => setConfirm("revert")} onRepair={() => void repair()} />}
      {r.history.length > 0 && <details className="text-xs text-muted-foreground"><summary className="flex cursor-pointer items-center gap-1.5"><History className="size-3.5" />History</summary><ul className="mt-1.5 space-y-0.5 pl-5">{r.history.map((h, i) => <li key={i}>{new Date(h.ts * 1000).toLocaleString()} · {h.event}</li>)}</ul></details>}

      <ConfirmDialog open={confirm === "apply"} onOpenChange={(o) => !o && setConfirm(null)} loading={apply.isPending} title={unverified ? "Apply an unverified fix?" : "Apply this verified fix?"} confirmLabel="Apply"
        description={<div className="space-y-2"><p>Writes {approved.length} approved file{approved.length === 1 ? "" : "s"} to the project copy, then runs the tests and linter.</p>
          {unverified && <p className="rounded-md bg-warning/10 p-2 text-warning">This fix is a suggestion: {v ? v.summary : "no verification result is attached"}.</p>}
          {deletes.length > 0 && <p className="rounded-md bg-destructive/10 p-2 text-destructive">This patch deletes: {deletes.map((f) => f.path).join(", ")}.</p>}</div>} onConfirm={() => apply.mutate()} />
      <ConfirmDialog open={confirm === "revert"} onOpenChange={(o) => !o && setConfirm(null)} title="Revert this patch?" description="Restores the files exactly as they were before the patch was applied." confirmLabel="Revert" tone="destructive" loading={busy === "revert"} onConfirm={() => void act("revert", () => api.revertPatch(patchId), "Patch reverted")} />
      <ConfirmDialog open={confirm === "reject"} onOpenChange={(o) => !o && setConfirm(null)} title="Reject this patch?" description="The patch is marked rejected and cannot be applied. Your project is not changed." confirmLabel="Reject" tone="destructive" loading={busy === "reject"} onConfirm={() => void act("reject", () => api.rejectPatch(patchId), "Patch rejected")} />
    </div>
  );
}
