"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronsUpDown, FolderGit2, GitBranch, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useInvalidateRepo } from "@/hooks/queries";
import { useCurrentRepo } from "@/hooks/useCurrentRepo";
import { useUi } from "@/lib/ui";
import { cn } from "@/lib/utils";
import { Dropdown, DropdownContent, DropdownItem, DropdownLabel, DropdownSeparator, DropdownTrigger } from "@/components/ui/dropdown";
import { Dialog, DialogContent, DialogClose } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export function ProjectSwitcher({ collapsed }: { collapsed?: boolean }) {
  const { repo, repos, repoId, setRepoId } = useCurrentRepo();
  const setAdd = useUi((s) => s.setAddProject);
  const invalidate = useInvalidateRepo();
  const [syncing, setSyncing] = useState(false);
  const sync = async () => {
    if (!repoId) return;
    setSyncing(true);
    const t = toast.loading("Syncing from the original source and re-indexing…");
    try { await api.refreshRepo(repoId); invalidate(repoId); qc.invalidateQueries({ queryKey: ["repos"] }); qc.invalidateQueries(); toast.success("Project synced: the agent now sees your latest files", { id: t }); }
    catch (e) { toast.error((e as Error).message, { id: t }); } finally { setSyncing(false); }
  };
  const qc = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const del = useMutation({
    mutationFn: () => api.deleteRepo(repoId!),
    onSuccess: () => { toast.success(`Removed ${repo?.name}`); setConfirmDelete(false); setRepoId(null); qc.invalidateQueries({ queryKey: ["repos"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <>
      <Dropdown>
        <DropdownTrigger asChild>
          <button aria-label="Switch project" className={cn("flex w-full items-center gap-2.5 rounded-lg bg-panel px-2.5 py-2 text-left shadow-card transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60", collapsed && "justify-center px-0")}>
            <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary"><FolderGit2 className="size-3.5" /></span>
            {!collapsed && (<>
              <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{repo?.name ?? "No project"}</span><span className="flex items-center gap-1 truncate text-[11px] text-muted-foreground">{repo?.branch ? <><GitBranch className="size-3" />{repo.branch}</> : "Add a repository"}</span></span>
              <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
            </>)}
          </button>
        </DropdownTrigger>
        <DropdownContent align="start" className="w-64">
          <DropdownLabel>Projects</DropdownLabel>
          {repos.length === 0 && <div className="px-2 py-2 text-xs text-muted-foreground">No projects yet.</div>}
          {repos.map((r) => (
            <DropdownItem key={r.id} checked={r.id === repoId} icon={<FolderGit2 />} onSelect={() => setRepoId(r.id)}>
              <span className="block truncate">{r.name}</span><span className="block truncate text-[11px] text-muted-foreground">{r.files} files{r.branch ? ` · ${r.branch}` : ""}</span>
            </DropdownItem>
          ))}
          <DropdownSeparator />
          <DropdownItem icon={<Plus />} onSelect={() => setAdd(true)}>Add project…</DropdownItem>
          {repoId && <DropdownItem icon={<RefreshCw className={syncing ? "animate-spin" : ""} />} onSelect={() => void sync()}>Sync from source & re-index</DropdownItem>}
          {repoId && <DropdownItem icon={<Trash2 />} className="text-destructive data-[highlighted]:text-destructive" onSelect={() => setConfirmDelete(true)}>Remove project…</DropdownItem>}
        </DropdownContent>
      </Dropdown>
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent title="Remove project" description="Removes the project copy and its index from this server.">
          <div className="space-y-3 p-5">
            <h2 className="text-sm font-semibold">Remove “{repo?.name}”?</h2>
            <p className="text-xs leading-relaxed text-muted-foreground">This deletes the server’s working copy and index of this project. Your original repository on GitHub or disk is not touched. Unapplied patches for it will no longer be reachable.</p>
            <div className="flex justify-end gap-2"><DialogClose asChild><Button variant="outline" size="sm">Cancel</Button></DialogClose><Button variant="destructive" size="sm" loading={del.isPending} onClick={() => del.mutate()}>Remove</Button></div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
