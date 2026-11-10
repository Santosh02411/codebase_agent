import type {
  GitStatus, GitVersions, GrepResult, Health, RepoMeta, SymbolInfo, TerminalResult, TestRun, Chunk, Edit, NewFile,
  PatchRecord, PatchFileVersions, ResultData, SandboxStatus, QualityInfo, QualityJob, QualityReport, GhPull, GhIssue, GitSummary, ActionRecord, ActionPreview, DatasetInfo, ExperimentJob, ExperimentResult, ExperimentSummary, RagInfo,
  QualityHistoryItem, RepoFiles, StaticReview, SourceStatus, FlowResult, SystemGraph, Insights, OverviewData, OverviewResponse, ExplainResponse, TestDiscovery, RecordedRun, AuthStatus, BranchInfo, CommitInfo, GithubRepo, Graph, Impact, IndexStatus, RemotePreview, RepoStats, SymbolDetail,
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
    throw new ApiError(`Can't reach the API at ${API_URL || "this server"}. Is the backend running? (uvicorn app.main:app --reload)`, 0);
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
  checkout: (id: string, ref: string, force = false) => request<RepoMeta>(`/repositories/${id}/checkout`, json("POST", { ref, force, approved: force })),   // force only after the user confirmed
  fetchHistory: (id: string, deepen = 50) => request<{ shallow: boolean }>(`/repositories/${id}/fetch`, json("POST", { deepen })),
  symbol: (id: string, symbolId: string) => request<SymbolDetail>(`/repositories/${id}/symbol?${qs({ id: symbolId })}`),
  graphCalls: (id: string, symbol: string, depth: number, direction: string) => request<Graph>(`/repositories/${id}/graph/calls?${qs({ symbol, depth, direction })}`),
  graphModules: (id: string, path: string | undefined, depth: number, direction: string) => request<Graph>(`/repositories/${id}/graph/modules?${qs({ path, depth, direction })}`),
  impact: (id: string, path: string) => request<Impact>(`/repositories/${id}/impact?${qs({ path })}`),
  authStatus: () => request<AuthStatus>("/auth/status"),
  githubRepos: (q: string) => request<GithubRepo[]>(`/github/repos?${qs({ q })}`),
  githubLogout: () => request<{ connected: boolean }>("/auth/github/logout", { method: "POST" }),
  ragInfo: () => request<RagInfo>("/rag/info"),
  datasets: () => request<DatasetInfo[]>("/experiments/datasets"),
  experiments: () => request<ExperimentSummary[]>("/experiments"),
  experiment: (id: string) => request<ExperimentResult>(`/experiments/${id}`),
  experimentJob: (id: string) => request<ExperimentJob>(`/experiments/jobs/${id}`),
  runExperiment: (body: { repo_id: string; dataset: string; embedders: string[]; rerankers: string[]; use_pgvector: boolean }) =>
    request<{ job_id: string }>("/experiments", json("POST", body)),
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
  gitDiscard: (repo_id: string, path: string) => request<GitStatus>("/git/discard", json("POST", { repo_id, path, approved: true })),   // callers confirm with the user first
  gitCommit: (repo_id: string, message: string) => request<{ sha: string }>("/git/commit", json("POST", { repo_id, message })),
  runTests: (repo_id: string, targets?: string[]) => request<TestRun>("/run-tests", json("POST", { repo_id, targets })),
  terminal: (repo_id: string, command: string) => request<TerminalResult>("/terminal/exec", json("POST", { repo_id, command })),
  applyChanges: (repo_id: string, edits: Edit[], new_files: NewFile[]) =>
    request<{ files: string[]; index: RepoMeta }>("/apply-changes", json("POST", { repo_id, edits, new_files })),
  sandbox: () => request<SandboxStatus>("/sandbox/status"),
  qualityInfo: (repo_id: string) => request<QualityInfo>(`/quality/analyzers?${qs({ repo_id })}`),
  qualityRun: (repo_id: string, tools?: string[], coverage = true) => request<{ id: string }>("/quality/run", json("POST", { repo_id, tools, coverage })),
  qualityJob: (id: string) => request<QualityJob>(`/quality/jobs/${id}`),
  qualityLatest: (repo_id: string) => request<QualityReport | null>(`/quality/latest?${qs({ repo_id })}`),
  gitSummary: (repo_id: string) => request<GitSummary>(`/git/summary?${qs({ repo_id })}`),
  gitBranch: (repo_id: string, name: string) => request<{ branch: string }>("/git/branch", json("POST", { repo_id, name })),
  commitMessage: (repo_id: string, provider?: string, issue?: number) => request<{ message: string; files: string[]; secret_files: string[] }>("/git/commit-message", json("POST", { repo_id, provider: provider || undefined, issue })),
  prDescription: (repo_id: string, base: string, head: string, provider?: string, issue?: number) => request<{ title: string; body: string }>("/git/pr-description", json("POST", { repo_id, base, head, provider: provider || undefined, issue })),
  ghPulls: (repo_id: string) => request<GhPull[]>(`/github/pulls?${qs({ repo_id })}`),
  ghIssues: (repo_id: string) => request<GhIssue[]>(`/github/issues?${qs({ repo_id })}`),
  ghAnalyze: (repo_id: string, number: number, provider?: string) => request<ResultData>("/github/pr/analyze", json("POST", { repo_id, number, provider: provider || undefined })),
  ghReview: (repo_id: string, number: number, provider?: string) => request<ResultData>("/github/pr/review", json("POST", { repo_id, number, provider: provider || undefined })),
  ghFixIssue: (repo_id: string, number: number, provider?: string) => request<ResultData>("/github/issue/fix", json("POST", { repo_id, number, provider: provider || undefined })),
  actions: (repo_id: string) => request<ActionRecord[]>(`/actions?${qs({ repo_id })}`),
  proposePush: (repo_id: string, branch?: string, force = false) => request<ActionRecord>("/actions/push", json("POST", { repo_id, branch, force })),
  proposePr: (repo_id: string, v: { title: string; body: string; base: string; head: string; draft: boolean }) => request<ActionRecord>("/actions/pull-request", json("POST", { repo_id, ...v })),
  proposeReview: (repo_id: string, number: number, body: string, event: string, comments: { path: string; line: number; body: string; severity?: string }[]) => request<ActionRecord>("/actions/review", json("POST", { repo_id, number, body, event, comments })),
  approveAction: (id: string, confirm_text = "") => request<ActionRecord>(`/actions/${id}/approve`, json("POST", { approved: true, confirm_text })),
  rejectAction: (id: string) => request<ActionRecord>(`/actions/${id}/reject`, { method: "POST" }),
  patch: (id: string) => request<PatchRecord>(`/patches/${id}`),
  patchFile: (id: string, path: string) => request<PatchFileVersions>(`/patches/${id}/file?${qs({ path })}`),
  applyPatch: (id: string, files: string[] | undefined, runChecks = true) => request<PatchRecord>(`/patches/${id}/apply`, json("POST", { approved: true, files, run_checks: runChecks })),
  revertPatch: (id: string, force = false) => request<PatchRecord>(`/patches/${id}/revert`, json("POST", { force })),
  rejectPatch: (id: string) => request<PatchRecord>(`/patches/${id}/reject`, { method: "POST" }),
  recheckPatch: (id: string) => request<PatchRecord>(`/patches/${id}/checks`, { method: "POST" }),
  repairPatch: (id: string, provider?: string) => request<ResultData>(`/patches/${id}/repair`, json("POST", { provider: provider || undefined })),
  reviewStatic: (id: string, paths?: string[]) => request<StaticReview>(`/repositories/${id}/review/static`, json("POST", { paths: paths ?? null })),
  reviewSnippet: (filename: string, text: string) => request<StaticReview>(`/review/snippet`, json("POST", { filename, text })),
  sourceStatus: (id: string) => request<SourceStatus>(`/repositories/${id}/source-status`),
  refreshRepo: (id: string) => request<Record<string, unknown>>(`/repositories/${id}/refresh`, json("POST", {})),
  flow: (id: string, symbol: string, depth = 3) => request<FlowResult>(`/repositories/${id}/flow?${qs({ symbol, depth })}`),
  repoFiles: (id: string) => request<RepoFiles>(`/repositories/${id}/files`),
  graphSystem: (id: string, maxSymbols = 900) => request<SystemGraph>(`/repositories/${id}/graph/system?${qs({ max_symbols: maxSymbols })}`),
  insights: (id: string) => request<Insights>(`/repositories/${id}/insights`),
  overview: (id: string) => request<{ overview: OverviewData | null; stale: boolean; llm_mock: boolean }>(`/repositories/${id}/overview`),
  makeOverview: (id: string, force = false, provider?: string) => request<OverviewResponse>(`/repositories/${id}/overview`, json("POST", { force, provider: provider || null })),
  explain: (repo_id: string, subject: string, paths: string[], symbols: string[], provider?: string) => request<ExplainResponse>(`/explain`, json("POST", { repo_id, subject, paths, symbols, provider: provider || null })),
  testDiscovery: (id: string) => request<TestDiscovery>(`/repositories/${id}/tests`),
  testRuns: (id: string, limit = 20, full = true) => request<RecordedRun[]>(`/repositories/${id}/test-runs?${qs({ limit, full })}`),
  deleteRepo: (id: string) => request<{ deleted: string } | Record<string, unknown>>(`/repositories/${id}`, { method: "DELETE" }),
  patches: (repo_id: string) => request<PatchRecord[]>(`/patches?${qs({ repo_id })}`),
  qualityHistory: (repo_id: string) => request<QualityHistoryItem[]>(`/quality/history?${qs({ repo_id })}`),
  createPr: (repo_id: string, files: Record<string, string>, title: string, body: string) =>
    request<{ url: string; number: number; branch: string }>("/create-pr", json("POST", { repo_id, files, title, body, confirm: true })),
};
