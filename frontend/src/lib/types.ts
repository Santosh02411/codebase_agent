// Shapes returned by the FastAPI backend (see app/main.py).
export interface RepoMeta { id: string; name: string; source: string; files: number; chunks: number; embedder: string; indexed_at: string }
export interface Health { status: string; llm_provider: string; embedding_provider: string; llm_model: string; github_configured: boolean; git_available: boolean; allow_local_paths: boolean }
export interface Chunk { id: number; file: string; kind: string; name: string; qualname: string; start: number; end: number; text: string; via: string; route: string; score?: number }
export interface SymbolInfo { name: string; qualname: string; kind: string; file: string; start: number; end: number; route?: string }
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
