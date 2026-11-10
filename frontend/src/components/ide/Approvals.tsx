"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink, GitPullRequest, MessageSquareText, Upload } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ActionRecord } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export const usePendingActions = (repoId: string | null) =>
  useQuery({ queryKey: ["actions", repoId], queryFn: () => api.actions(repoId!), enabled: !!repoId, refetchInterval: 15_000 });

const ICON = { push: <Upload className="size-4" />, force_push: <Upload className="size-4 text-red-400" />, create_pr: <GitPullRequest className="size-4" />, post_review: <MessageSquareText className="size-4" /> };

/** What would happen, in full, before anything leaves this machine. Approval happens here and only here. */
export function ApprovalCard({ a, repoId }: { a: ActionRecord; repoId: string }) {
  const qc = useQueryClient();
  const p = a.preview;
  const [typed, setTyped] = useState("");
  const done = useMutation({
    mutationFn: () => api.approveAction(a.id, typed),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["actions", repoId] }); qc.invalidateQueries({ queryKey: ["git"] }); toast.success(r.kind === "create_pr" ? "Pull request opened" : r.kind === "post_review" ? "Review posted" : "Pushed"); },
    onError: (e: Error) => { qc.invalidateQueries({ queryKey: ["actions", repoId] }); toast.error(e.message); },
  });
  const reject = useMutation({ mutationFn: () => api.rejectAction(a.id), onSuccess: () => qc.invalidateQueries({ queryKey: ["actions", repoId] }) });
  const pending = a.status === "pending";
  const url = (a.result?.url as string | undefined) ?? undefined;
  return (
    <div className={cn("space-y-2 rounded-lg border p-2.5", a.destructive ? "border-red-500/50 bg-red-500/5" : pending ? "border-amber-500/40 bg-amber-500/5" : "opacity-80")}>
      <div className="flex items-start gap-2 font-medium">{ICON[a.kind]}<span className="min-w-0 flex-1">{p.title}</span><Badge variant={a.status === "executed" ? "success" : a.status === "pending" ? "warning" : "secondary"}>{a.status}</Badge></div>
      {a.external && pending && <div className="text-[11px] text-muted-foreground">Externally visible: nothing happens until you approve.</div>}
      {p.warnings.map((w, i) => <div key={i} className="flex gap-1.5 text-[11.5px] text-amber-200"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{w}</div>)}
      {(a.kind === "push" || a.kind === "force_push") && (
        <div className="space-y-1 text-[12px]">
          <div className="font-mono text-[11px] text-muted-foreground">{p.url} ← {p.branch}</div>
          {(p.commits ?? []).slice(0, 8).map((c) => <div key={c.sha} className="truncate">• <span className="font-mono text-[11px] text-muted-foreground">{c.short ?? c.sha.slice(0, 8)}</span> {c.subject}</div>)}
          {(p.commit_count ?? 0) > 8 && <div className="text-muted-foreground">… and {(p.commit_count ?? 0) - 8} more commits</div>}
          {(p.files ?? []).length > 0 && <div className="text-[11px] text-muted-foreground">{(p.files ?? []).length} file(s): {(p.files ?? []).slice(0, 6).map((f) => f.path).join(", ")}</div>}
        </div>
      )}
      {a.kind === "create_pr" && <div className="space-y-1 text-[12px]"><div className="font-mono text-[11px] text-muted-foreground">{p.repo}: {p.head} → {p.base}{p.draft ? " (draft)" : ""}</div><div className="font-semibold">{p.pr_title}</div><pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-background/60 p-2 text-[11px]">{p.body || "(no description)"}</pre></div>}
      {a.kind === "post_review" && (
        <div className="space-y-1 text-[12px]">
          <div className="text-[11px] text-muted-foreground">{p.repo}#{p.number} · {p.event}</div>
          <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-background/60 p-2 text-[11px]">{p.body || "(no summary)"}</pre>
          {(p.comments ?? []).slice(0, 10).map((c, i) => <div key={i} className="rounded bg-background/60 p-1.5"><span className="font-mono text-[11px] text-muted-foreground">{c.path}:{c.line}</span> {c.body}</div>)}
        </div>
      )}
      {pending ? (
        <div className="space-y-1.5">
          {p.confirm_text && <Input placeholder={`Type “${p.confirm_text}” to confirm`} value={typed} onChange={(e) => setTyped(e.target.value)} />}
          <div className="flex gap-1.5">
            <Button size="sm" variant={a.destructive ? "destructive" : "default"} disabled={done.isPending || (!!p.confirm_text && typed !== p.confirm_text)} onClick={() => done.mutate()}>{done.isPending ? "Working…" : a.destructive ? "Approve (destructive)" : "Approve"}</Button>
            <Button size="sm" variant="outline" disabled={done.isPending} onClick={() => reject.mutate()}>Reject</Button>
          </div>
        </div>
      ) : url ? <a className="flex items-center gap-1 text-[12px] text-primary hover:underline" href={url} target="_blank" rel="noreferrer"><ExternalLink className="size-3" />{url}</a>
        : a.result && "error" in a.result ? <div className="text-[12px] text-red-300">{String(a.result.error)}</div> : null}
    </div>
  );
}
