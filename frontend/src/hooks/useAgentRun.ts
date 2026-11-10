"use client";
import { useCallback } from "react";
import { toast } from "sonner";
import { useIde } from "@/store/ide";
import { streamAgent } from "@/lib/stream";
import { editKey, newKey } from "@/lib/edits";
import type { AgentEvent, Mode, Proposal, ResultData, Source } from "@/lib/types";
import { uid } from "@/lib/utils";

const LABEL: Record<Mode, string> = {
  chat: "Ask", debug: "Debug & fix", fix: "Propose fix", change: "Change code", tests: "Write tests", review: "Review", architecture: "Architecture",
};

function toProposal(mode: Mode, d: ResultData, title: string): Proposal | null {
  const edits = d.edits?.length ? d.edits : d.patch ? [d.patch] : [];
  const newFiles = d.new_files ?? [];
  if (!edits.length && !newFiles.length) return null;
  const decisions: Proposal["decisions"] = {};
  edits.forEach((_, i) => (decisions[editKey(i)] = "pending"));
  newFiles.forEach((n) => (decisions[newKey(n.path)] = "pending"));
  return {
    id: uid(), title, origin: mode, explanation: d.explanation || d.patch?.explanation || "", edits: edits.map(({ file, search, replace }) => ({ file, search, replace })),
    newFiles, decisions, testBefore: d.test_before, testAfter: d.test_after, status: d.status, applied: false, discarded: false,
  };
}

/** Starts an agent run and streams every event into the store (chat message, activity timeline, sources, tests). */
let currentAbort: AbortController | null = null;   // module scope: the run keeps going (and can be stopped) when the user navigates between pages

export function useAgentRun() {
  const abort = { get current() { return currentAbort; }, set current(v: AbortController | null) { currentAbort = v; } };

  const stop = useCallback(() => currentAbort?.abort(), []);

  const run = useCallback(async (mode: Mode, text: string, opts: { target?: string } = {}) => {
    const s = useIde.getState();
    if (!s.repoId) { toast.error("Open or add a repository first"); return; }
    if (s.runs.some((r) => r.state === "running")) { toast.message("The agent is still working — stop it first or wait"); return; }

    const attachment = s.attachment ?? undefined;
    const question = attachment
      ? `${text}\n\nSelected code (${attachment.file}:${attachment.startLine}-${attachment.endLine}):\n\`\`\`\n${attachment.text}\n\`\`\``
      : text;
    const runId = uid(), msgId = uid();
    const label = text.trim().slice(0, 60) || opts.target || LABEL[mode];

    const shots = s.screenshots;
    s.addMessage({ id: uid(), role: "user", mode, text: text || (shots.length ? "See the attached screenshot." : LABEL[mode]), attachment, shots: shots.length ? shots : undefined, ts: Date.now() });
    s.clearScreenshots();
    s.addMessage({ id: msgId, role: "assistant", mode, text: "", runId, state: "running", ts: Date.now() });
    s.startRun({ id: runId, mode, label, started: Date.now(), state: "running", events: [] });
    s.setAttachment(null);
    s.setBottom("activity");

    const ctl = new AbortController();
    abort.current = ctl;
    let finished = false;

    const onEvent = (e: AgentEvent) => {
      const st = useIde.getState();
      st.appendEvent(runId, e);
      if (e.type === "tool" && e.phase === "end" && e.name === "run_tests") {
        // the tool summary carries status only; full output arrives with the result
      }
      if (e.type === "result") {
        finished = true;
        const d = e.data;
        const sources: Source[] = d.sources ?? [];
        if (d.conversation_id) st.setConversationId(d.conversation_id);
        // a patch the server stored is reviewed from the server's exact before/after text; the client-side proposal is only the fallback
        const proposal = d.patch_id ? null : toProposal(mode, d, label);
        if (proposal) st.addProposal(proposal);
        if (d.test_before) st.addTest(`${LABEL[mode]} · before change`, d.test_before);
        if (d.test_after) st.addTest(`${LABEL[mode]} · after change`, d.test_after);
        st.patchMessage(msgId, { state: "done", result: d, sources, findings: d.findings, proposalId: proposal?.id, patchId: d.patch_id ?? undefined });
        st.finishRun(runId, "done");
        if (d.patch_id) { st.openPatch(d.patch_id, label); toast.success("A patch is ready to review. Nothing has been changed yet."); }
        else if (proposal) { st.openReview(proposal.id); toast.success("A change is ready to review"); }
        else if (d.findings) st.setBottom("problems");
        else if (sources.length && mode === "chat") st.setBottom("sources");
      } else if (e.type === "error") {
        finished = true;
        st.patchMessage(msgId, { state: "error", error: e.message });
        st.finishRun(runId, "error");
      }
    };

    try {
      await streamAgent({ repo_id: s.repoId, mode, text: question, target: opts.target, provider: s.provider, verify: s.verify, conversation_id: s.conversationId ?? undefined,
        images: shots.length ? shots.map(({ media_type, data }) => ({ media_type, data })) : undefined }, onEvent, ctl.signal);
      if (!finished) { useIde.getState().patchMessage(msgId, { state: "error", error: "The stream ended without a result" }); useIde.getState().finishRun(runId, "error"); }
    } catch (err) {
      const st = useIde.getState();
      if ((err as Error).name === "AbortError") {
        st.patchMessage(msgId, { state: "cancelled" });
        st.finishRun(runId, "cancelled");
      } else {
        st.patchMessage(msgId, { state: "error", error: (err as Error).message });
        st.finishRun(runId, "error");
      }
    } finally {
      abort.current = null;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { run, stop };
}
