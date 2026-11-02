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
export interface Chunk { id: number; file: string; kind: string; name: string; qualname: string; start: number; end: number; text: string; via: string; route: string; score?: number }
export interface SymbolInfo { id: string; name: string; qualname: string; kind: string; file: string; start: number; end: number; route?: string; signature?: string; doc?: string; parent?: string }
export interface Source { file: string; lines: string; symbol: string }
export interface TestRun { status: string; passed: boolean; summary: string; output: string }
export interface Step { node: string; message: string }
export interface Edit { file: string; search: string; replace: string; explanation?: string }
export interface NewFile { path: string; content: string }
export interface Finding { file: string; line: number; severity: "high" | "medium" | "low"; message: string; source?: string }
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
  | (Base & { type: "node"; node: string; phase: "start" | "end" })
  | (Base & { type: "tool"; name: string; args: string; phase: "start" | "end" | "error"; summary?: string; hits?: Source[]; ms?: number; error?: string })
  | (Base & { type: "llm"; task: string; model: string; phase: "start" | "end" | "error"; ms?: number; prompt_chars?: number; error?: string })
  | (Base & { type: "step"; node: string; message: string })
  | (Base & { type: "status"; message: string })
  | (Base & { type: "result"; mode: Mode; data: ResultData })
  | (Base & { type: "error"; message: string });

export interface ResultData {
  run_id?: string; llm?: string; status?: string; answer?: string; summary?: string; explanation?: string;
  intent?: string; analysis?: Record<string, unknown>; steps?: Step[]; sources?: Source[];
  patch?: Edit | null; diff?: string; test_before?: TestRun | null; test_after?: TestRun | null;
  edits?: Edit[]; new_files?: NewFile[]; files?: string[]; final_files?: Record<string, string>;
  findings?: Finding[]; facts?: unknown;
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
  sources?: Source[];
  findings?: Finding[];
  ts: number;
}

export interface Run { id: string; mode: Mode; label: string; started: number; ended?: number; state: "running" | "done" | "error" | "cancelled"; events: AgentEvent[] }
export interface TestEntry { id: string; ts: number; origin: string; run: TestRun }
export interface TermLine { id: string; kind: "cmd" | "out" | "err"; text: string }
