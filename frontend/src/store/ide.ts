import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AgentEvent, ChatMessage, Decision, Mode, Proposal, Run, ScreenshotIn, TermLine, TestEntry, TestRun } from "@/lib/types";
import { basename, uid } from "@/lib/utils";

export type SidebarView = "explorer" | "search" | "repo" | "experiments" | "git" | "github";
export type BottomTab = "activity" | "terminal" | "tests" | "sources" | "problems";
export type PaletteMode = "files" | "symbols" | "workspace" | "commands";

export interface GraphFocus { mode: "calls" | "modules"; focus?: string }
export interface Tab { id: string; kind: "file" | "review" | "patch" | "quality" | "diff" | "graph" | "experiment"; experimentId?: string; path?: string; proposalId?: string; patchId?: string; title: string; graph?: GraphFocus }
export interface Selection { file: string; startLine: number; endLine: number; text: string }
export interface Reveal { path: string; line: number; endLine: number; nonce: number }

interface IdeState {
  repoId: string | null;
  setRepoId: (id: string | null) => void;

  sidebar: SidebarView; setSidebar: (v: SidebarView) => void;
  bottom: BottomTab; bottomOpen: boolean; setBottom: (t: BottomTab, open?: boolean) => void; toggleBottom: () => void;
  chatOpen: boolean; toggleChat: () => void; setChatOpen: (v: boolean) => void;
  palette: PaletteMode | null; setPalette: (m: PaletteMode | null) => void;

  tabs: Tab[]; activeTabId: string | null;
  openFile: (path: string, line?: number, endLine?: number) => void;
  openReview: (proposalId: string) => void;
  openPatch: (patchId: string, title: string) => void;
  openQuality: () => void;
  openDiff: (path: string) => void;
  openGraph: (mode: "calls" | "modules", focus: string | undefined, title: string) => void;
  openExperiment: (id: string, title: string) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  reveal: Reveal | null;

  buffers: Record<string, string>; setBuffer: (path: string, text: string | null) => void;
  cursor: { line: number; col: number }; setCursor: (line: number, col: number) => void;
  selection: Selection | null; setSelection: (s: Selection | null) => void;
  attachment: Selection | null; setAttachment: (s: Selection | null) => void;
  screenshots: ScreenshotIn[]; addScreenshot: (s: ScreenshotIn) => void; removeScreenshot: (i: number) => void; clearScreenshots: () => void;
  conversationId: string | null; setConversationId: (id: string | null) => void;

  mode: Mode; setMode: (m: Mode) => void;
  provider: string; setProvider: (p: string) => void;
  verify: boolean; setVerify: (v: boolean) => void;

  messages: ChatMessage[];
  resetChat: () => void;
  addMessage: (m: ChatMessage) => void;
  patchMessage: (id: string, p: Partial<ChatMessage>) => void;

  runs: Run[]; activeRunId: string | null;
  startRun: (r: Run) => void;
  appendEvent: (runId: string, e: AgentEvent) => void;
  finishRun: (runId: string, state: Run["state"]) => void;
  setActiveRun: (id: string) => void;

  proposals: Record<string, Proposal>;
  addProposal: (p: Proposal) => void;
  patchProposal: (id: string, p: Partial<Proposal>) => void;
  setDecision: (id: string, key: string, d: Decision) => void;
  setAllDecisions: (id: string, d: Decision) => void;

  termLines: TermLine[]; termHistory: string[];
  pushTerm: (lines: Omit<TermLine, "id">[]) => void; pushHistory: (c: string) => void; clearTerm: () => void;

  testRuns: TestEntry[]; addTest: (origin: string, run: TestRun) => void;
}

const SESSION = {
  tabs: [] as Tab[], activeTabId: null as string | null, reveal: null as Reveal | null, buffers: {} as Record<string, string>,
  selection: null as Selection | null, attachment: null as Selection | null, screenshots: [] as ScreenshotIn[], conversationId: null as string | null, messages: [] as ChatMessage[], runs: [] as Run[],
  activeRunId: null as string | null, proposals: {} as Record<string, Proposal>, termLines: [] as TermLine[], termHistory: [] as string[],
  testRuns: [] as TestEntry[],
};

export const useIde = create<IdeState>()(
  persist(
    (set) => ({
      repoId: null,
      setRepoId: (id) => set((s) => (s.repoId === id ? s : { ...SESSION, repoId: id })),

      sidebar: "explorer", setSidebar: (sidebar) => set({ sidebar }),
      bottom: "activity", bottomOpen: true,
      setBottom: (bottom, open = true) => set((s) => ({ bottom, bottomOpen: open ? true : s.bottomOpen })),
      toggleBottom: () => set((s) => ({ bottomOpen: !s.bottomOpen })),
      chatOpen: true, toggleChat: () => set((s) => ({ chatOpen: !s.chatOpen })), setChatOpen: (chatOpen) => set({ chatOpen }),
      palette: null, setPalette: (palette) => set({ palette }),

      tabs: [], activeTabId: null, reveal: null,
      openFile: (path, line, endLine) =>
        set((s) => {
          const id = `file:${path}`;
          const tabs = s.tabs.some((t) => t.id === id) ? s.tabs : [...s.tabs, { id, kind: "file" as const, path, title: basename(path) }];
          return {
            tabs, activeTabId: id,
            reveal: line ? { path, line, endLine: endLine ?? line, nonce: Date.now() } : s.reveal,
          };
        }),
      openReview: (proposalId) =>
        set((s) => {
          const id = `review:${proposalId}`;
          const title = `Review: ${s.proposals[proposalId]?.title ?? "changes"}`;
          return { tabs: s.tabs.some((t) => t.id === id) ? s.tabs : [...s.tabs, { id, kind: "review" as const, proposalId, title }], activeTabId: id };
        }),
      openQuality: () =>
        set((s) => ({ tabs: s.tabs.some((t) => t.id === "quality") ? s.tabs : [...s.tabs, { id: "quality", kind: "quality" as const, title: "Code quality" }], activeTabId: "quality" })),
      openPatch: (patchId, title) =>
        set((s) => {
          const id = `patch:${patchId}`;
          return { tabs: s.tabs.some((t) => t.id === id) ? s.tabs : [...s.tabs, { id, kind: "patch" as const, patchId, title: `Patch: ${title}`.slice(0, 48) }], activeTabId: id };
        }),
      openDiff: (path) =>
        set((s) => {
          const id = `diff:${path}`;
          return { tabs: s.tabs.some((t) => t.id === id) ? s.tabs : [...s.tabs, { id, kind: "diff" as const, path, title: `${basename(path)} (changes)` }], activeTabId: id };
        }),
      openGraph: (mode, focus, title) =>
        set((s) => {
          const id = `graph:${mode}:${focus ?? "*"}`;
          const tab: Tab = { id, kind: "graph", title, graph: { mode, focus } };
          return { tabs: s.tabs.some((t) => t.id === id) ? s.tabs : [...s.tabs, tab], activeTabId: id };
        }),
      openExperiment: (experimentId, title) =>
        set((s) => {
          const id = `experiment:${experimentId}`;
          return { tabs: s.tabs.some((t) => t.id === id) ? s.tabs : [...s.tabs, { id, kind: "experiment" as const, experimentId, title }], activeTabId: id };
        }),
      closeTab: (id) =>
        set((s) => {
          const i = s.tabs.findIndex((t) => t.id === id);
          const tabs = s.tabs.filter((t) => t.id !== id);
          const activeTabId = s.activeTabId === id ? (tabs[Math.min(i, tabs.length - 1)]?.id ?? null) : s.activeTabId;
          return { tabs, activeTabId };
        }),
      setActiveTab: (activeTabId) => set({ activeTabId }),

      buffers: {},
      setBuffer: (path, text) =>
        set((s) => {
          const buffers = { ...s.buffers };
          if (text === null) delete buffers[path]; else buffers[path] = text;
          return { buffers };
        }),
      cursor: { line: 1, col: 1 }, setCursor: (line, col) => set({ cursor: { line, col } }),
      selection: null, setSelection: (selection) => set({ selection }),
      attachment: null, setAttachment: (attachment) => set({ attachment }),
      screenshots: [], addScreenshot: (sc) => set((s) => ({ screenshots: [...s.screenshots, sc].slice(0, 3) })),
      removeScreenshot: (i) => set((s) => ({ screenshots: s.screenshots.filter((_, j) => j !== i) })), clearScreenshots: () => set({ screenshots: [] }),
      conversationId: null, setConversationId: (conversationId) => set({ conversationId }),

      mode: "chat", setMode: (mode) => set({ mode }),
      provider: "", setProvider: (provider) => set({ provider }),
      verify: true, setVerify: (verify) => set({ verify }),

      messages: [],
      resetChat: () => set({ messages: [], runs: [], activeRunId: null, conversationId: null, proposals: {}, attachment: null, screenshots: [] }),
      addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
      patchMessage: (id, p) => set((s) => ({ messages: s.messages.map((m) => (m.id === id ? { ...m, ...p } : m)) })),

      runs: [], activeRunId: null,
      startRun: (r) => set((s) => ({ runs: [...s.runs, r], activeRunId: r.id })),
      appendEvent: (runId, e) => set((s) => ({ runs: s.runs.map((r) => (r.id === runId ? { ...r, events: [...r.events, e] } : r)) })),
      finishRun: (runId, state) => set((s) => ({ runs: s.runs.map((r) => (r.id === runId ? { ...r, state, ended: Date.now() } : r)) })),
      setActiveRun: (activeRunId) => set({ activeRunId }),

      proposals: {},
      addProposal: (p) => set((s) => ({ proposals: { ...s.proposals, [p.id]: p } })),
      patchProposal: (id, p) => set((s) => (s.proposals[id] ? { proposals: { ...s.proposals, [id]: { ...s.proposals[id], ...p } } } : s)),
      setDecision: (id, key, d) =>
        set((s) => (s.proposals[id] ? { proposals: { ...s.proposals, [id]: { ...s.proposals[id], decisions: { ...s.proposals[id].decisions, [key]: d } } } } : s)),
      setAllDecisions: (id, d) =>
        set((s) => {
          const p = s.proposals[id];
          if (!p) return s;
          return { proposals: { ...s.proposals, [id]: { ...p, decisions: Object.fromEntries(Object.keys(p.decisions).map((k) => [k, d])) } } };
        }),

      termLines: [], termHistory: [],
      pushTerm: (lines) => set((s) => ({ termLines: [...s.termLines, ...lines.map((l) => ({ ...l, id: uid() }))].slice(-800) })),
      pushHistory: (c) => set((s) => ({ termHistory: [...s.termHistory.filter((x) => x !== c), c].slice(-50) })),
      clearTerm: () => set({ termLines: [] }),

      testRuns: [],
      addTest: (origin, run) => set((s) => ({ testRuns: [{ id: uid(), ts: Date.now(), origin, run }, ...s.testRuns].slice(0, 40) })),
    }),
    {
      name: "codebase-agent-ide",
      partialize: (s) => ({ repoId: s.repoId, sidebar: s.sidebar, bottom: s.bottom, bottomOpen: s.bottomOpen, chatOpen: s.chatOpen, mode: s.mode, provider: s.provider, verify: s.verify }),
    },
  ),
);
