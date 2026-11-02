import type {
  GitStatus, GitVersions, GrepResult, Health, RepoMeta, SymbolInfo, TerminalResult, TestRun, Chunk, Edit, NewFile,
  AuthStatus, BranchInfo, CommitInfo, GithubRepo, Graph, Impact, IndexStatus, RemotePreview, RepoStats, SymbolDetail,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(`Can't reach the API at ${API_URL}. Is the backend running? (uvicorn app.main:app --reload)`, 0);
  }
  let data: unknown = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const d = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(typeof d === "string" ? d : d ? JSON.stringify(d) : res.statusText, res.status);
  }
  return data as T;
}

const json = (method: string, body: unknown): RequestInit => ({ method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const qs = (o: Record<string, string | number | boolean | undefined>) =>
  Object.entries(o).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");

export const api = {
  health: () => request<Health>("/health"),
  repos: () => request<RepoMeta[]>("/repositories"),
  addRepo: (source: string, name?: string, branch?: string) => request<RepoMeta>("/repositories", json("POST", { source, name: name || undefined, branch: branch || undefined })),
  preview: (source: string) => request<RemotePreview>("/repositories/preview", json("POST", { source })),
  status: (id: string) => request<IndexStatus>(`/repositories/${id}/status`),
  activeIndexing: () => request<Record<string, IndexStatus>>("/indexing"),
  stats: (id: string) => request<RepoStats>(`/repositories/${id}/stats`),
  branches: (id: string) => request<BranchInfo>(`/repositories/${id}/branches`),
  commits: (id: string, ref: string | undefined, limit: number, skip: number) => request<CommitInfo[]>(`/repositories/${id}/commits?${qs({ ref, limit, skip })}`),
  checkout: (id: string, ref: string, force = false) => request<RepoMeta>(`/repositories/${id}/checkout`, json("POST", { ref, force })),
  fetchHistory: (id: string, deepen = 50) => request<{ shallow: boolean }>(`/repositories/${id}/fetch`, json("POST", { deepen })),
  symbol: (id: string, symbolId: string) => request<SymbolDetail>(`/repositories/${id}/symbol?${qs({ id: symbolId })}`),
  graphCalls: (id: string, symbol: string, depth: number, direction: string) => request<Graph>(`/repositories/${id}/graph/calls?${qs({ symbol, depth, direction })}`),
  graphModules: (id: string, path: string | undefined, depth: number, direction: string) => request<Graph>(`/repositories/${id}/graph/modules?${qs({ path, depth, direction })}`),
  impact: (id: string, path: string) => request<Impact>(`/repositories/${id}/impact?${qs({ path })}`),
  authStatus: () => request<AuthStatus>("/auth/status"),
  githubRepos: (q: string) => request<GithubRepo[]>(`/github/repos?${qs({ q })}`),
  githubLogout: () => request<{ connected: boolean }>("/auth/github/logout", { method: "POST" }),
  githubLoginUrl: () => `${API_URL}/auth/github/login`,
  uploadRepo: (file: File, name: string) => {
    const f = new FormData();
    f.append("file", file);
    f.append("name", name);
    return request<RepoMeta>("/repositories/upload", { method: "POST", body: f });
  },
  reindex: (id: string) => request<RepoMeta>(`/repositories/${id}/index`, { method: "POST" }),
  tree: (id: string) => request<{ files: string[] }>(`/repositories/${id}/tree`),
  file: (id: string, path: string) => request<{ path: string; text: string; truncated: boolean }>(`/repositories/${id}/file?${qs({ path })}`),
  saveFile: (id: string, path: string, text: string) => request<RepoMeta>(`/repositories/${id}/file`, json("PUT", { path, text })),
  symbols: (id: string, o: { path?: string; q?: string }) => request<SymbolInfo[]>(`/repositories/${id}/symbols?${qs({ ...o, limit: 400 })}`),
  grep: (id: string, q: string, regex: boolean, caseSensitive: boolean) =>
    request<GrepResult>(`/repositories/${id}/grep?${qs({ q, regex, case: caseSensitive })}`),
  search: (repo_id: string, query: string, k = 10) => request<Chunk[]>("/search", json("POST", { repo_id, query, k })),
  gitStatus: (id: string) => request<GitStatus>(`/repositories/${id}/git/status`),
  gitFile: (id: string, path: string) => request<GitVersions>(`/repositories/${id}/git/file?${qs({ path })}`),
  gitDiscard: (repo_id: string, path: string) => request<GitStatus>("/git/discard", json("POST", { repo_id, path })),
  gitCommit: (repo_id: string, message: string) => request<{ sha: string }>("/git/commit", json("POST", { repo_id, message })),
  runTests: (repo_id: string) => request<TestRun>("/run-tests", json("POST", { repo_id })),
  terminal: (repo_id: string, command: string) => request<TerminalResult>("/terminal/exec", json("POST", { repo_id, command })),
  applyChanges: (repo_id: string, edits: Edit[], new_files: NewFile[]) =>
    request<{ files: string[]; index: RepoMeta }>("/apply-changes", json("POST", { repo_id, edits, new_files })),
  createPr: (repo_id: string, files: Record<string, string>, title: string, body: string) =>
    request<{ url: string; number: number; branch: string }>("/create-pr", json("POST", { repo_id, files, title, body, confirm: true })),
};
