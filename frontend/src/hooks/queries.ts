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
    for (const k of ["tree", "file", "symbols", "git", "gitfile", "grep", "semantic", "repos"]) qc.invalidateQueries({ queryKey: [k] });
    void id;
  };
}

export function useAddRepo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { source?: string; file?: File; name: string }) => (v.file ? api.uploadRepo(v.file, v.name || v.file.name.replace(/\.zip$/i, "")) : api.addRepo(v.source!, v.name)),
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
