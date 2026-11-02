"use client";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Edit, NewFile } from "@/lib/types";

export const useHealth = () => useQuery({ queryKey: ["health"], queryFn: api.health, retry: false, refetchInterval: 15000 });
export const useRepos = () => useQuery({ queryKey: ["repos"], queryFn: api.repos });
export const useTree = (id: string | null) => useQuery({ queryKey: ["tree", id], queryFn: () => api.tree(id!), enabled: !!id, select: (d) => d.files });
export const useFile = (id: string | null, path: string | undefined) =>
  useQuery({ queryKey: ["file", id, path], queryFn: () => api.file(id!, path!), enabled: !!id && !!path, staleTime: 30_000 });
export const useFileSymbols = (id: string | null, path: string | undefined) =>
  useQuery({ queryKey: ["symbols", id, "file", path], queryFn: () => api.symbols(id!, { path }), enabled: !!id && !!path, staleTime: 30_000 });
export const useRepoSymbols = (id: string | null, q = "") =>
  useQuery({ queryKey: ["symbols", id, "repo", q], queryFn: () => api.symbols(id!, { q }), enabled: !!id, staleTime: 30_000, placeholderData: keepPreviousData });
export const useGitStatus = (id: string | null) =>
  useQuery({ queryKey: ["git", id], queryFn: () => api.gitStatus(id!), enabled: !!id, refetchOnWindowFocus: true });
export const useGitVersions = (id: string | null, path: string | undefined) =>
  useQuery({ queryKey: ["gitfile", id, path], queryFn: () => api.gitFile(id!, path!), enabled: !!id && !!path });

export const useTextSearch = (id: string | null, q: string, regex: boolean, caseSensitive: boolean) =>
  useQuery({ queryKey: ["grep", id, q, regex, caseSensitive], queryFn: () => api.grep(id!, q, regex, caseSensitive), enabled: !!id && q.length >= 2, retry: false });
export const useSemanticSearch = (id: string | null, q: string) =>
  useQuery({ queryKey: ["semantic", id, q], queryFn: () => api.search(id!, q, 10), enabled: !!id && q.length >= 2, retry: false });

/** Everything that depends on the repository's files. */
export function useInvalidateRepo() {
  const qc = useQueryClient();
  return (id: string) => {
    for (const k of ["tree", "file", "symbols", "git", "gitfile", "grep", "semantic", "repos", "stats", "callgraph", "modgraph", "symbol", "impact"]) qc.invalidateQueries({ queryKey: [k] });
    void id;
  };
}

export function useAddRepo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { source?: string; file?: File; name: string; branch?: string }) => (v.file ? api.uploadRepo(v.file, v.name || v.file.name.replace(/\.zip$/i, "")) : api.addRepo(v.source!, v.name, v.branch)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["repos"] }),
  });
}

export function useReindex() {
  const inv = useInvalidateRepo();
  return useMutation({
    mutationFn: (id: string) => api.reindex(id),
    onSuccess: (_d, id) => { inv(id); toast.success("Repository re-indexed"); },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function useSaveFile(id: string | null) {
  const inv = useInvalidateRepo();
  return useMutation({
    mutationFn: (v: { path: string; text: string }) => api.saveFile(id!, v.path, v.text),
    onSuccess: () => id && inv(id),
    onError: (e: Error) => toast.error(`Save failed: ${e.message}`),
  });
}

export function useApplyChanges(id: string | null) {
  const inv = useInvalidateRepo();
  return useMutation({
    mutationFn: (v: { edits: Edit[]; newFiles: NewFile[] }) => api.applyChanges(id!, v.edits, v.newFiles),
    onSuccess: () => id && inv(id),
    onError: (e: Error) => toast.error(e.message),
  });
}

// ---- repository management & code intelligence --------------------------------------------------------
export const useStats = (id: string | null) => useQuery({ queryKey: ["stats", id], queryFn: () => api.stats(id!), enabled: !!id, staleTime: 5_000 });
export const useBranches = (id: string | null) => useQuery({ queryKey: ["branches", id], queryFn: () => api.branches(id!), enabled: !!id });
export const useCommits = (id: string | null, ref: string | undefined, limit: number) =>
  useQuery({ queryKey: ["commits", id, ref, limit], queryFn: () => api.commits(id!, ref, limit, 0), enabled: !!id, placeholderData: keepPreviousData });
export const useAuthStatus = () => useQuery({ queryKey: ["auth"], queryFn: api.authStatus, retry: false });
export const useGithubRepos = (q: string, enabled: boolean) =>
  useQuery({ queryKey: ["ghrepos", q], queryFn: () => api.githubRepos(q), enabled, retry: false, staleTime: 30_000 });
/** Progress of imports/re-indexes that are running right now (polls only while something is indexing). */
export const useActiveIndexing = (enabled = true) =>
  useQuery({ queryKey: ["indexing"], queryFn: api.activeIndexing, enabled, refetchInterval: (q) => (q.state.data && Object.keys(q.state.data).length ? 500 : 2000) });
export const useSymbolDetail = (id: string | null, symbolId: string | undefined) =>
  useQuery({ queryKey: ["symbol", id, symbolId], queryFn: () => api.symbol(id!, symbolId!), enabled: !!id && !!symbolId });
export const useCallGraph = (id: string | null, symbol: string | undefined, depth: number, direction: string) =>
  useQuery({ queryKey: ["callgraph", id, symbol, depth, direction], queryFn: () => api.graphCalls(id!, symbol!, depth, direction), enabled: !!id && !!symbol });
export const useModuleGraph = (id: string | null, path: string | undefined, depth: number, direction: string, enabled = true) =>
  useQuery({ queryKey: ["modgraph", id, path ?? "*", depth, direction], queryFn: () => api.graphModules(id!, path, depth, direction), enabled: !!id && enabled });
export const useImpact = (id: string | null, path: string | undefined) =>
  useQuery({ queryKey: ["impact", id, path], queryFn: () => api.impact(id!, path!), enabled: !!id && !!path });

export function useCheckout(id: string | null) {
  const inv = useInvalidateRepo();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { ref: string; force?: boolean }) => api.checkout(id!, v.ref, v.force),
    onSuccess: (meta) => {
      if (id) inv(id);
      for (const k of ["stats", "branches", "commits", "callgraph", "modgraph", "symbol", "impact"]) qc.invalidateQueries({ queryKey: [k] });
      const r = meta.last_index;
      toast.success(r ? `Switched to ${meta.branch || meta.commit}: ${r.files_changed + r.files_added + r.files_removed} files re-indexed, ${r.files_unchanged} reused` : "Switched");
    },
  });
}

export function useFetchHistory(id: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.fetchHistory(id!, 50),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["commits"] }); qc.invalidateQueries({ queryKey: ["branches"] }); toast.success("Loaded more history"); },
    onError: (e: Error) => toast.error(e.message),
  });
}
