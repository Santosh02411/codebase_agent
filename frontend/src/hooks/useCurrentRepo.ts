"use client";
import { useEffect } from "react";
import { useRepos } from "@/hooks/queries";
import { useIde } from "@/store/ide";

/** The selected project. Falls back to the first project when the remembered one no longer exists. */
export function useCurrentRepo() {
  const repos = useRepos();
  const repoId = useIde((s) => s.repoId);
  const setRepoId = useIde((s) => s.setRepoId);
  const list = repos.data ?? [];
  const repo = list.find((r) => r.id === repoId) ?? null;
  useEffect(() => {
    if (!repos.data) return;
    if (repoId && !repo) setRepoId(repos.data[0]?.id ?? null);
    else if (!repoId && repos.data.length) setRepoId(repos.data[0].id);
  }, [repos.data, repoId, repo, setRepoId]);
  return { repoId: repo?.id ?? null, repo, repos: list, isLoading: repos.isLoading, error: repos.error, refetch: repos.refetch, setRepoId };
}
