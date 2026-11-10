"use client";
import { useState } from "react";
import { GitBranch, GitCommitHorizontal, RefreshCw, Sparkles, Undo2, Upload } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useGitStatus, useInvalidateRepo } from "@/hooks/queries";
import { api } from "@/lib/api";
import { useIde } from "@/store/ide";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { FileIcon } from "./Explorer";
import { ApprovalCard, usePendingActions } from "./Approvals";

const COLOR = { modified: "text-amber-400", added: "text-emerald-400", untracked: "text-emerald-400", deleted: "text-red-400" } as const;
const LETTER = { modified: "M", added: "A", untracked: "U", deleted: "D" } as const;

export function GitPanel({ repoId }: { repoId: string }) {
  const git = useGitStatus(repoId);
  const qc = useQueryClient();
  const inv = useInvalidateRepo();
  const openDiff = useIde((s) => s.openDiff);
  const closeTab = useIde((s) => s.closeTab);
  const [msg, setMsg] = useState("");
  const [branchName, setBranchName] = useState("");
  const provider = useIde((s) => s.provider);
  const actions = usePendingActions(repoId);
  const draft = useMutation({
    mutationFn: () => api.commitMessage(repoId, provider),
    onSuccess: (r) => { setMsg(r.message); if (r.secret_files.length) toast.warning(`Not committed (look like secrets): ${r.secret_files.join(", ")}`); },
    onError: (e: Error) => toast.error(e.message),
  });
  const newBranch = useMutation({
    mutationFn: () => api.gitBranch(repoId, branchName.trim()),
    onSuccess: (r) => { setBranchName(""); qc.invalidateQueries({ queryKey: ["git"] }); inv(repoId); toast.success(`Created and switched to ${r.branch}`); },
    onError: (e: Error) => toast.error(e.message),
  });
  const push = useMutation({
    mutationFn: () => api.proposePush(repoId),
    onSuccess: () => { actions.refetch(); toast.message("Review the push below. Nothing is sent until you approve it."); },
    onError: (e: Error) => toast.error(e.message),
  });

  const discard = useMutation({
    mutationFn: (path: string) => api.gitDiscard(repoId, path),
    onSuccess: (_d, path) => { closeTab(`diff:${path}`); useIde.getState().setBuffer(path, null); inv(repoId); toast.success(`Discarded changes to ${path}`); },
    onError: (e: Error) => toast.error(e.message),
  });
  const commit = useMutation({
    mutationFn: () => api.gitCommit(repoId, msg),
    onSuccess: (r) => { setMsg(""); qc.invalidateQueries({ queryKey: ["git"] }); qc.invalidateQueries({ queryKey: ["gitfile"] }); toast.success(`Committed ${r.sha} in the project copy`); },
    onError: (e: Error) => toast.error(e.message),
  });

  const files = git.data?.files ?? [];
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center px-3 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span>Git changes</span>
        <button className="ml-auto rounded p-1 hover:bg-accent" title="Refresh" onClick={() => git.refetch()}><RefreshCw className={cn("size-3", git.isFetching && "animate-spin")} /></button>
      </div>
      {git.data && !git.data.available && <div className="px-3 text-muted-foreground">git isn’t installed on the server, so changes can’t be tracked.</div>}
      {git.error && <div className="px-3 text-destructive">{(git.error as Error).message}</div>}
      {git.data?.available && (
        <>
          <div className="flex items-center gap-1.5 px-3 pb-2 text-muted-foreground"><GitBranch className="size-3.5" />{git.data.branch}<span className="ml-auto">{files.length} changed</span></div>
          <div className="space-y-2 px-2 pb-2">
            <div className="flex gap-1.5"><Input placeholder="New branch name" value={branchName} onChange={(e) => setBranchName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && branchName.trim()) newBranch.mutate(); }} /><Button size="sm" variant="outline" disabled={!branchName.trim() || newBranch.isPending} onClick={() => newBranch.mutate()}>Create</Button></div>
            <Input placeholder="Commit message (project copy)" value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && msg.trim() && files.length) commit.mutate(); }} />
            <Button size="sm" variant="outline" className="w-full" disabled={!files.length || draft.isPending} onClick={() => draft.mutate()}><Sparkles /> {draft.isPending ? "Drafting…" : "Draft message with AI"}</Button>
            <Button size="sm" className="w-full" disabled={!msg.trim() || !files.length || commit.isPending} onClick={() => commit.mutate()}><GitCommitHorizontal /> Commit {files.length ? `${files.length} file${files.length > 1 ? "s" : ""}` : ""}</Button>
          </div>
          <ScrollArea className="min-h-0 flex-1">
            {files.length === 0 && <div className="px-3 py-3 text-muted-foreground">No changes yet. Edits you save and AI changes you approve show up here, compared with the imported version.</div>}
            {files.map((f) => (
              <div key={f.path} className="group flex h-7 items-center gap-1.5 px-3 hover:bg-accent/60">
                <button className="flex min-w-0 flex-1 items-center gap-1.5 text-left" onClick={() => openDiff(f.path)} title="View diff">
                  <FileIcon name={f.path} /><span className="truncate">{f.path}</span>
                </button>
                <button className="hidden rounded p-1 hover:bg-background group-hover:block" title="Discard changes" onClick={() => confirm(`Discard changes to ${f.path}?`) && discard.mutate(f.path)}><Undo2 className="size-3.5" /></button>
                <span className={cn("w-3 text-center text-[10px] font-semibold", COLOR[f.status])}>{LETTER[f.status]}</span>
              </div>
            ))}
          </ScrollArea>
          <div className="space-y-2 border-t px-2 py-2">
            <Button size="sm" variant="outline" className="w-full" disabled={push.isPending} onClick={() => push.mutate()} title="Shows exactly what would be pushed. Nothing is sent until you approve."><Upload /> Push branch… (needs approval)</Button>
            {(actions.data ?? []).filter((a) => a.status === "pending").map((a) => <ApprovalCard key={a.id} a={a} repoId={repoId} />)}
            <div className="text-[11px] text-muted-foreground">Commits stay in the server’s project copy until you approve a push. Pull requests and reviews are in the GitHub panel.</div>
          </div>
        </>
      )}
    </div>
  );
}
