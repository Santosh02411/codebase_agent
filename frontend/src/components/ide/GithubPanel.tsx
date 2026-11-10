"use client";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Bug, CircleDot, Eye, GitPullRequest, RefreshCw, Search } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ResultData } from "@/lib/types";
import { cn, uid } from "@/lib/utils";
import { useIde } from "@/store/ide";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ApprovalCard, usePendingActions } from "./Approvals";

/** Pull requests and issues of the connected GitHub repository, the workflows built on them, and every operation waiting for your approval. */
export function GithubPanel({ repoId }: { repoId: string }) {
  const provider = useIde((s) => s.provider);
  const [tab, setTab] = useState<"prs" | "issues" | "approvals">("prs");
  const pulls = useQuery({ queryKey: ["ghpulls", repoId], queryFn: () => api.ghPulls(repoId), retry: false });
  const issues = useQuery({ queryKey: ["ghissues", repoId], queryFn: () => api.ghIssues(repoId), retry: false, enabled: tab === "issues" });
  const actions = usePendingActions(repoId);
  const pending = (actions.data ?? []).filter((a) => a.status === "pending");
  const [busy, setBusy] = useState<string | null>(null);
  const seen = useRef(0);
  useEffect(() => { if (pending.length > seen.current) setTab("approvals"); seen.current = pending.length; }, [pending.length]);   // a new proposal opens the approvals list

  const run = async (key: string, label: string, fn: () => Promise<ResultData>, mode: "chat" | "review" | "debug") => {
    setBusy(key);
    useIde.getState().addMessage({ id: uid(), role: "user", mode, text: label, ts: Date.now() });
    try {
      const d = await fn();
      useIde.getState().addMessage({ id: uid(), role: "assistant", mode, text: "", state: "done", result: d, sources: d.sources, patchId: d.patch_id ?? undefined, ts: Date.now() });
      if (d.patch_id) { useIde.getState().openPatch(d.patch_id, label); toast.success("A patch is ready to review. Nothing has been changed yet."); } else toast.success("Done: see the chat");
      useIde.getState().setChatOpen(true);
    } catch (e) { toast.error((e as Error).message); } finally { setBusy(null); }
  };

  const err = (pulls.error as Error | null)?.message;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"><span>GitHub</span>
        <button className="ml-auto rounded p-1 hover:bg-accent" title="Refresh" onClick={() => { pulls.refetch(); issues.refetch(); actions.refetch(); }}><RefreshCw className={cn("size-3", pulls.isFetching && "animate-spin")} /></button></div>
      <div className="flex gap-1 px-2 pb-2">
        {([["prs", "Pull requests"], ["issues", "Issues"], ["approvals", `Approvals${pending.length ? ` (${pending.length})` : ""}`]] as const).map(([id, t]) => (
          <button key={id} className={cn("rounded px-2 py-1 text-[12px]", tab === id ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/60")} onClick={() => setTab(id)}>{t}</button>))}
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {err && tab !== "approvals" && <div className="space-y-2 px-3 py-2 text-[12px] text-muted-foreground"><div className="text-destructive">{err}</div><div>Add the project from a GitHub URL or the GitHub repository list, and connect GitHub in the Repository panel.</div></div>}
        {tab === "prs" && (pulls.data ?? []).map((p) => (
          <div key={p.number} className="space-y-1.5 border-b px-3 py-2">
            <div className="flex items-start gap-1.5"><GitPullRequest className="mt-0.5 size-3.5 shrink-0 text-emerald-400" /><a className="min-w-0 flex-1 hover:underline" href={p.url} target="_blank" rel="noreferrer"><span className="text-muted-foreground">#{p.number}</span> {p.title}</a>{p.draft && <Badge variant="secondary">draft</Badge>}</div>
            <div className="text-[11px] text-muted-foreground">{p.author} · {p.head} → {p.base}</div>
            <div className="flex gap-1.5">
              <Button size="xs" variant="outline" disabled={busy !== null} onClick={() => void run(`a${p.number}`, `Analyze PR #${p.number}: ${p.title}`, () => api.ghAnalyze(repoId, p.number, provider), "review")}><Search /> {busy === `a${p.number}` ? "Analyzing…" : "Analyze"}</Button>
              <Button size="xs" variant="outline" disabled={busy !== null} onClick={() => void run(`r${p.number}`, `Review PR #${p.number}: ${p.title}`, () => api.ghReview(repoId, p.number, provider), "review")}><Eye /> {busy === `r${p.number}` ? "Reviewing…" : "Review"}</Button>
            </div>
          </div>))}
        {tab === "prs" && !err && pulls.data?.length === 0 && <div className="px-3 py-3 text-muted-foreground">No open pull requests.</div>}
        {tab === "issues" && (issues.data ?? []).map((i) => (
          <div key={i.number} className="space-y-1.5 border-b px-3 py-2">
            <div className="flex items-start gap-1.5"><CircleDot className="mt-0.5 size-3.5 shrink-0 text-amber-400" /><a className="min-w-0 flex-1 hover:underline" href={i.url} target="_blank" rel="noreferrer"><span className="text-muted-foreground">#{i.number}</span> {i.title}</a></div>
            <div className="flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">{i.author} · {i.comments} comment(s){i.labels.map((l) => <Badge key={l} variant="outline">{l}</Badge>)}</div>
            <Button size="xs" disabled={busy !== null} onClick={() => void run(`i${i.number}`, `Fix issue #${i.number}: ${i.title}`, () => api.ghFixIssue(repoId, i.number, provider), "debug")}><Bug /> {busy === `i${i.number}` ? "Working on it…" : "Fix this issue"}</Button>
          </div>))}
        {tab === "issues" && !err && issues.data?.length === 0 && <div className="px-3 py-3 text-muted-foreground">No open issues.</div>}
        {tab === "approvals" && (
          <div className="space-y-2 p-2">
            {(actions.data ?? []).length === 0 && <div className="px-1 py-2 text-muted-foreground">Nothing waiting. Pushes, pull requests and posted reviews appear here with their full content, and only happen when you approve them.</div>}
            {(actions.data ?? []).map((a) => <ApprovalCard key={a.id} a={a} repoId={repoId} />)}
          </div>)}
      </ScrollArea>
    </div>
  );
}
