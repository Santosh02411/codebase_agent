// Shapes returned by the FastAPI backend (see app/main.py).
export interface IndexReport {
  mode: "full" | "incremental"; files_total: number; files_added: number; files_changed: number; files_removed: number; files_unchanged: number;
  chunks_total: number; chunks_embedded: number; chunks_reused: number; duration_ms: number; changed_files: string[]; parsers: Record<string, number>;
}
export interface RepoMeta {
  id: string; name: string; source: string; files: number; chunks: number; embedder: string; indexed_at: string;
  provider?: string; branch?: string; commit?: string; detached?: boolean; languages?: string[]; symbols?: number; last_index?: IndexReport;
}
export interface IndexStatus { state: "indexing" | "ready" | "error" | "unknown"; phase?: string; done?: number; total?: number; error?: string; report?: IndexReport }
export interface LangStat { language: string; files: number; lines: number; symbols: number }
export interface ApiItem { method: string; path: string; handler: string; file: string; line: number; framework: string }
export interface ModelItem { name: string; file: string; line: number; framework: string; fields: number }
export interface RepoStats {
  files: number; code_files: number; lines: number; comment_lines: number; todos: number; languages: LangStat[];
  symbols: { functions: number; methods: number; classes: number; interfaces: number; structs: number; enums: number; types: number; variables: number; total: number };
  dependencies: { declared: { name: string; ecosystem: string }[]; declared_count: number; external_imports: { name: string; files: number }[]; manifests: string[] };
  tests: { files: number; cases: number; file_list: string[] };
  apis: { count: number; items: ApiItem[] };
  models: ModelItem[];
  graph: { module_edges: number; files_with_imports: number; call_edges: number; calls_seen: number; call_resolution_pct: number; inheritance_edges: number };
  parsers: Record<string, number>; parse_errors: { file: string; errors: string[] }[];
  repo: { id: string; name: string; source: string; provider: string; branch: string; commit: string; detached: boolean };
  indexing: IndexStatus & { indexed_at?: string; embedder: string; chunks: number; last_index: IndexReport };
}
export interface Branch { name: string; sha: string; date: string; subject: string; current: boolean; remote: boolean }
export interface BranchInfo { current: string; commit: string; detached: boolean; default: string; branches: Branch[]; shallow: boolean }
export interface CommitInfo { sha: string; short: string; author: string; date: string; subject: string }
export interface RemotePreview { provider: string; name: string; branches: string[]; default: string }
export interface AuthStatus {
  github: { oauth_configured: boolean; connected: boolean; user: { login: string; name: string; avatar: string } | null; token_in_env: boolean };
  gitlab: { token_in_env: boolean; oauth: string }; bitbucket: { token_in_env: boolean; oauth: string };
}
export interface GithubRepo { full_name: string; private: boolean; default_branch: string; url: string; description: string; updated_at: string; language: string }
export interface SymbolRef { id: string; qualname: string; kind: string; file: string; start: number; end: number; confidence: string }
export interface SymbolDetail {
  id: string; name: string; qualname: string; kind: string; file: string; start: number; end: number; language: string; signature: string; doc: string;
  route: string; decorators: string[]; tags: string[]; bases: string[]; extra: Record<string, unknown>; exported: boolean;
  callers: SymbolRef[]; callees: SymbolRef[]; base_symbols: SymbolRef[]; derived: SymbolRef[]; unresolved_calls: string[];
}
export interface GraphNode { id: string; name: string; file: string; level?: number; kind?: string; qualname?: string; start?: number; end?: number; count?: number; signature?: string; language?: string; symbols?: number; external?: string[]; route?: string }
export interface GraphEdge { source: string; target: string; confidence?: string; weight?: number }
export interface Graph { nodes: GraphNode[]; edges: GraphEdge[]; collapsed?: boolean }
export interface Impact { file: string; dependents: { file: string; distance: number }[]; tests: string[] }
export interface Health { status: string; llm_provider: string; embedding_provider: string; llm_model: string; github_configured: boolean; git_available: boolean; allow_local_paths: boolean }
export interface Chunk { why?: string; id: number; file: string; kind: string; name: string; qualname: string; start: number; end: number; text: string; via: string; route: string; score?: number }
export interface SymbolInfo { id: string; name: string; qualname: string; kind: string; file: string; start: number; end: number; route?: string; signature?: string; doc?: string; parent?: string }
export interface Source { file: string; lines: string; symbol: string; cite?: number; cited?: boolean }
export interface TestFailure { id: string; kind: string; message: string; traceback?: string; frames?: { file: string; line: number; func: string }[]; location?: { file: string; line: number }; error?: string }
export interface TestOutcome { id: string; outcome: "passed" | "failed" | "error" | "skipped" | "xfail" | "xpass" }
export interface TestRun {
  status: string; passed: boolean; summary: string; output: string; command?: string; failed_tests?: TestFailure[]; counts?: Record<string, number>; duration_ms?: number; framework?: string; total?: number;
  sandbox?: { mode: string; image?: string; isolated?: boolean };
  /** true only when a process actually ran the tests; false for "sandbox unavailable", "no framework"... */
  executed?: boolean; executed_at?: number; exit_code?: number | null; stderr?: string; truncated?: boolean; tests?: TestOutcome[]; skipped_reasons?: Record<string, string>;
  run_id?: string; recorded_at?: number;
}
export interface RecordedRun { id: string; recorded_at: number; source: string; targets: string[]; run: TestRun }
export interface TestFileInfo { file: string; language: string; cases: { name: string; line: number }[]; covers_verified: string[]; covers_inferred: string[] }
export interface TestDiscovery { framework: string | null; language: string | null; command: string | null; files: TestFileInfo[]; file_count: number; case_count: number; can_execute: boolean; sandbox: { mode: string; isolated: boolean; problem?: string; warning?: string; docker_available?: boolean }; note: string | null }
export interface Step { node: string; message: string }
export interface Edit { file: string; search: string; replace: string; explanation?: string }
export interface NewFile { path: string; content: string }
export interface Finding {
  file: string; line: number; severity: "high" | "medium" | "low"; message: string; source?: string;
  /** added by backend v13: how sure the check is, the offending line, how to fix it, other sources that reported the same spot, whether an AI finding points at real code */
  confidence?: "high" | "medium" | "low"; evidence?: string; fix?: string; also?: string[]; grounded?: boolean;
}
export interface GrepMatch { file: string; line: number; col: number; length: number; text: string }
export interface GrepResult { matches: GrepMatch[]; truncated: boolean; files: number }
export interface GitFile { path: string; status: "modified" | "added" | "untracked" | "deleted"; code: string }
export interface GitStatus { available: boolean; branch: string; files: GitFile[] }
export interface GitVersions { path: string; original: string; modified: string; is_new: boolean; is_deleted: boolean }
export interface TerminalResult { output: string; exit_code: number; tests?: TestRun }

export type Mode = "chat" | "debug" | "fix" | "change" | "tests" | "review" | "architecture";

// ---- live agent events (POST /agent/stream) ------------------------------------------------------
interface Base { seq: number; ts: number }
export type AgentEvent =
  | (Base & { type: "run_start"; mode: Mode })
  | (Base & { type: "node"; node: string; agent?: string; phase: "start" | "end" })
  | (Base & { type: "tool"; name: string; args: string; phase: "start" | "end" | "error"; summary?: string; hits?: Source[]; ms?: number; error?: string })
  | (Base & { type: "llm"; task: string; model: string; phase: "start" | "end" | "error" | "repair"; ms?: number; prompt_chars?: number; error?: string; provider?: string; input_tokens?: number; output_tokens?: number; tool_calls?: number; attempt?: number })
  | (Base & { type: "step"; node: string; message: string })
  | (Base & { type: "status"; message: string })
  | (Base & { type: "result"; mode: Mode; data: ResultData })
  | (Base & { type: "error"; message: string });

// ---- debugging report & patch proposals (app/patches.py, app/agent/errors.py) -------------------------------
export interface ErrorReport {
  source: string; language: string; exception_type: string; message: string; category: string; file: string; line: number; function: string; code_line: string;
  variables: { name: string; evidence: string }[]; frames: { file: string; line: number; func: string }[]; chained: string[]; http_status: number;
  related_functions: { name: string; file: string; relation: string }[];
}
export interface AffectedFile { path: string; roles: string[]; detail: string }
export type VerdictStatus = "resolved" | "partial" | "no_regressions" | "unverified" | "not_resolved";
export interface Verdict { status: VerdictStatus; summary: string; reasons: string[]; fixed_tests: string[]; new_failures: string[]; remaining_failures: string[]; reproduced: boolean | null; lint_new: number; lint_new_blocking: number }
export interface LintIssue { file: string; line: number; code: string; message: string; severity: string; blocking: boolean }
export interface LintRun { tool: string; status: string; summary: string; counts?: { total: number; errors: number; warnings: number; blocking: number }; issues?: LintIssue[] }
export interface PatchFile { path: string; op: "modify" | "create" | "delete"; additions: number; deletions: number; fuzzy: boolean; notes: string[] }
export interface PatchChecks {
  status: "passed" | "failed" | "inconclusive"; tests_before?: TestRun | null; tests_after?: TestRun | null; lint_before?: LintRun | null; lint_after?: LintRun | null;
  lint_new: LintIssue[]; verdict: Verdict; ran_at: number;
}
export interface PatchRecord {
  id: string; repo_id: string; title: string; explanation: string; status: "proposed" | "applied" | "rejected" | "reverted"; parent_id: string | null;
  origin: { intent?: string; question?: string; run_id?: string }; files: PatchFile[]; stats: { files: number; additions: number; deletions: number; created: number; deleted: number; modified: number };
  verification?: { verdict?: Verdict; test_before?: TestRun | null; test_after?: TestRun | null; regression?: { tests: string[]; failed_before: boolean; passed_after: boolean } | null } | null;
  checks: PatchChecks | null; history: { ts: number; event: string }[]; applied_files: string[]; diff: string; created: number; index?: RepoMeta;
}
export interface PatchFileVersions { path: string; op: "modify" | "create" | "delete"; original: string; modified: string; diff: string }
export interface ScreenshotIn { media_type: string; data: string; name?: string }

export interface ResultData {
  pr_report?: PRReport | null; test_patterns?: Record<string, unknown> | null; coverage_delta?: { before: number; after: number; files: { path: string; before: number; after: number }[] } | null; impl_change?: boolean; issue?: { number: number; title: string; url: string };
  patch_id?: string | null; patch_files?: PatchFile[]; verification?: Verdict | null; error_report?: ErrorReport | null; affected_files?: AffectedFile[];
  regression?: { tests: string[]; failed_before: boolean; passed_after: boolean } | null; lint?: { tool: string; summary: string; new: LintIssue[] } | null; delete_files?: string[];
  run_id?: string; llm?: string; status?: string; answer?: string; summary?: string; explanation?: string;
  conversation_id?: string; plan?: { intent?: string; steps?: { agent: string; goal: string }[]; rationale?: string };
  context?: { kept: number; tokens: number; budget: number; by_source?: Record<string, number>; injection_flags?: { cite: number; file: string; lines: string; examples: string[] }[] };
  usage?: { calls: number; input_tokens: number; output_tokens: number; total_tokens: number; latency_ms: number; cost_usd?: number };
  review?: { approved: boolean; summary?: string; feedback?: string } | null;
  intent?: string; analysis?: Record<string, unknown>; steps?: Step[]; sources?: Source[];
  patch?: Edit | null; diff?: string; test_before?: TestRun | null; test_after?: TestRun | null;
  edits?: Edit[]; new_files?: NewFile[]; files?: string[]; final_files?: Record<string, string>;
  findings?: Finding[]; facts?: unknown; citations?: { cited: number[]; invalid: number[]; references?: { grounded?: string[]; unretrieved?: string[]; invalid?: string[] } };
}

// ---- client-side models ----------------------------------------------------------------------------
export type Decision = "pending" | "accepted" | "rejected";

export interface Proposal {
  id: string;
  title: string;
  origin: Mode;
  explanation: string;
  edits: Edit[];
  newFiles: NewFile[];
  /** keys: `e:<index>` for an edit, `n:<path>` for a new file */
  decisions: Record<string, Decision>;
  testBefore?: TestRun | null;
  testAfter?: TestRun | null;
  status?: string;
  applied: boolean;
  discarded: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  mode: Mode;
  text: string;
  attachment?: { file: string; startLine: number; endLine: number; text: string };
  runId?: string;
  state?: "running" | "done" | "error" | "cancelled";
  error?: string;
  result?: ResultData;
  proposalId?: string;
  patchId?: string;
  shots?: ScreenshotIn[];
  sources?: Source[];
  findings?: Finding[];
  ts: number;
}

export interface Run { id: string; mode: Mode; label: string; started: number; ended?: number; state: "running" | "done" | "error" | "cancelled"; events: AgentEvent[] }
export interface TestEntry { id: string; ts: number; origin: string; run: TestRun }
export interface TermLine { id: string; kind: "cmd" | "out" | "err"; text: string }

// ---- RAG pipeline & experiments ------------------------------------------------------------------------------
export interface RagInfo {
  store: "memory" | "pgvector"; embedding: { name: string; dim: number; error: string }; reranker: string;
  retrieval: { mode: string; rrf_k: number; candidates: number; vector_weight: number; keyword_weight: number };
  context_token_budget: number; models: { model: string; dim: number; table: string; hnsw: boolean; vectors: number }[]; database_error?: string;
}
export interface DatasetInfo { name: string; questions: number; description: string; repo: string }
export interface ExperimentSummary { id: string; created: string; dataset: string; questions: number; store: string; configs: number; skipped: number; best: { name: string; mrr: number } | null }
export interface MetricStat { mean: number; lo: number; hi: number }
export interface ExpConfigResult {
  config: { name: string; embedder: string; mode: string; reranker: string; vector_weight: number; pool: number };
  status: "ok" | "skipped" | "failed"; reason?: string; n?: number;
  summary?: Record<"symbol" | "file", Record<string, MetricStat>>;
  latency_ms?: { mean: number; p50: number; p95: number };
  per_question?: { id: string; question: string; tags: string[]; first_relevant_rank: number | null; expected: string[]; retrieved: string[] }[];
}
export interface ExperimentResult {
  id: string; created: string; dataset: { name: string; questions: number }; repo: string; store: string; ks: number[]; baseline: string | null;
  indexes: Record<string, { embedder: string; dim: number; chunks: number; seconds: number; embed_calls: number; embed_tokens: number }>;
  skipped_embedders: Record<string, string>; label_problems: string[]; configs: ExpConfigResult[];
  comparisons: Record<string, Record<string, { delta: number; p: number }>>; elapsed_s: number;
}
export interface ExperimentJob { id: string; state: "running" | "done" | "error"; phase: string; done: number; total: number; result_id: string | null; error: string }

// ---- sandbox, quality ------------------------------------------------------------------------------------------------------------------
export interface SandboxStatus { mode: "docker" | "local"; isolated: boolean; docker_available?: boolean; problem?: string; warning?: string }
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export interface QFinding { tool: string; category: string; file: string; line: number; code: string; message: string; severity: Severity; blocking: boolean; cwe: string; fix: string }
export interface QAnalyzer { tool: string; category: string; status: "ok" | "issues" | "unavailable" | "skipped" | "timeout" | "error"; findings: QFinding[]; summary: string; duration_ms: number; note: string }
export interface QCoverageFile { path: string; percent: number; covered: number; total: number; missing: string[] }
export interface QDimension { score: number; weight: number; detail: string }
export interface QualityReport {
  id: string; created: number; duration_s: number; repo_id?: string; sandbox: SandboxStatus; frameworks: string[]; notes: string[];
  tests: (TestRun & { framework?: string; total?: number })[]; coverage: { tool: string; percent: number; covered: number; total: number; files: QCoverageFile[] } | null;
  analyzers: Record<string, QAnalyzer>; findings: Record<string, Record<string, number>>;
  maintainability: { available: boolean; functions?: number; too_complex_or_long?: number; avg_complexity?: number; worst?: { name: string; file: string; line: number; length: number; complexity: number }[] };
  score: { overall: number | null; grade: string; dimensions: Record<string, QDimension>; not_measured: string[] };
}
export interface QualityJob { id: string; repo_id: string; status: "running" | "done" | "error"; progress: { ts: number; message: string }[]; report: QualityReport | null; error: string | null }
export interface QualityInfo { frameworks: string[]; analyzers: { name: string; label: string; category: string; applies: boolean }[] }

// ---- GitHub, git intelligence, approvals ------------------------------------------------------------------------------------------------
export interface GhPull { number: number; title: string; state: string; draft: boolean; author: string; base: string; head: string; head_sha: string; url: string; updated_at: string; labels: string[] }
export interface GhIssue { number: number; title: string; state: string; author: string; labels: string[]; comments: number; url: string; updated_at: string }
export interface GitSummary { current: string; commit: string; default: string; branches: string[]; remotes: { name: string; url: string }[]; recent: { short: string; author: string; date: string; subject: string }[]; contributors: { author: string; commits: number }[] }
export interface ActionPreview {
  title: string; warnings: string[]; confirm_text: string | null; destructive?: boolean;
  branch?: string; url?: string; commits?: { short?: string; sha: string; subject: string }[]; commit_count?: number; files?: { path: string; status: string; additions: number; deletions: number }[]; creates_remote_branch?: boolean;
  repo?: string; pr_title?: string; body?: string; base?: string; head?: string; draft?: boolean; event?: string; comments?: { path: string; line: number; body: string; severity?: string }[]; comment_count?: number; number?: number;
}
export interface ActionRecord { id: string; repo_id: string; kind: "push" | "force_push" | "create_pr" | "post_review"; preview: ActionPreview; status: "pending" | "executed" | "rejected" | "failed" | "expired" | "stale"; external: boolean; destructive: boolean; created: number; result: Record<string, unknown> | null }
export interface PRReport {
  kind: "analysis" | "review"; number: number; summary: string; verdict?: "approve" | "comment" | "request_changes"; comments?: { path: string; line: number; severity: string; body: string; source?: string }[];
  risk?: "low" | "medium" | "high"; change_type?: string; concerns?: { file: string; line: number; severity: string; message: string }[]; static_note?: string; head_sha?: string;
}

export interface QualityHistoryItem { id: string; created: number; score: number | null; grade: string }


// ---- system graph, insights, AI understanding ------------------------------------------------------------------
export interface SgFolder { id: string; name: string; parent: string; files: number; depth: number }
export interface SgFile { id: string; name: string; folder: string; language: string; lines: number; symbols: number; is_test: boolean; tests: number; routes: { method: string; path: string; handler: string; line: number }[]; entry: "route" | "name" | null; imports: number; imported_by: number; external: string[] }
export interface SgSymbol { id: string; file: string; name: string; qualname: string; kind: string; start: number; end: number; route: string; callers: number; callees: number; parent: string }
export type SgEdgeType = "import" | "call" | "inherit" | "test" | "file_call";
export interface SgEdge { source: string; target: string; type: SgEdgeType; verified: boolean; basis: string; weight: number; label?: string }
export interface SystemGraph { folders: SgFolder[]; files: SgFile[]; symbols: SgSymbol[]; edges: SgEdge[]; stats: { files: number; symbols: number; edges: number; tested_modules: number; verified_edges: number; inferred_edges: number }; truncated: { files: number; symbols: number } }
export interface Insights {
  entry_points: { file: string; reason: string; detail: string }[];
  routes: { method: string; path: string; handler: string; file: string; line: number }[];
  models: { name: string; file: string; line: number; framework: string; fields: number }[];
  folders: { path: string; files: number; symbols: number; test_files: number; languages: Record<string, number> }[];
  key_modules: { file: string; imported_by: number; symbols: string[] }[];
  hubs: { qualname: string; file: string; line: number; callers: number; callees: number; id: string }[];
  external: { name: string; files: number }[];
  risks: { untested_modules: string[]; long_functions: { qualname: string; file: string; line: number; lines: number }[]; parse_errors: string[]; todos: number };
  suggested_questions: { question: string; mode: "chat" | "review"; basis: string }[];
  graph: SystemGraph["stats"]; languages: { language: string; files: number; lines: number }[];
}
export interface OverviewData { answer: string; sources: Source[]; citations?: ResultData["citations"]; llm?: string; usage?: ResultData["usage"]; indexed_at?: string; facts: string; created: number; status?: string }
export type OverviewResponse = { state: "cached" | "generated"; overview: OverviewData } | { state: "unavailable"; reason: string; overview: OverviewData | null };
export type ExplainResponse = ({ state: "generated" } & ResultData) | { state: "unavailable"; reason: string };

// ---- strict review, source sync, execution flow -----------------------------------------------------------------
export interface StaticFinding { id: string; rule: string; category: string; severity: "high" | "medium" | "low"; confidence: "high" | "medium" | "low"; file: string; line: number; col: number; end_col: number; message: string; fix: string; evidence: string; language: string; context: { n: number; text: string }[]; source: string }
export interface StaticReview {
  findings: StaticFinding[]; summary: { total: number; by_severity: Record<string, number>; by_category: Record<string, number>; by_rule: Record<string, number> };
  coverage: { files_analysed: number; languages: { language: string; files: number; findings: number; depth: string }[]; skipped: { file: string; reason: string }[]; not_analysed_types: string[] };
  limits: string[]; duration_ms: number; engine: string; scope: "project" | "file"; project: { id: string; name: string; indexed_at?: string };
}
export interface SourceStatus { syncable: boolean; kind: "local" | "git" | "upload"; source?: string; changed: { file: string; change: "added" | "modified" | "deleted" }[]; count: number | null; note?: string }
export interface FlowStep { depth: number; from: string; from_file: string; to: string; to_file: string; to_line: number; resolved: boolean; verified: boolean; label: string; id?: string | null; kind?: "call" | "render" }
export interface FlowResult { root: { id: string; name: string; qualname: string; file: string; line: number }; steps: FlowStep[]; participants: { file: string; label: string }[]; truncated: boolean }

export interface RepoFiles { files: { path: string; size: number; indexed: boolean }[]; skipped_dirs: string[]; truncated: boolean }
