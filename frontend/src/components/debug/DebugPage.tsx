"use client";
import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Bug, FileCode2, ImagePlus, Play, Square, X, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { useAgentRun } from "@/hooks/useAgentRun";
import { useIde } from "@/store/ide";
import { currentActivity } from "@/lib/activity";
import { parseLines } from "@/lib/utils";
import type { ChatMessage, ErrorReport } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Switch, PageHeader } from "@/components/ui/misc";
import { Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { FileLink, MockNotice } from "@/components/common/bits";
import { Markdown } from "@/components/common/Markdown";
import { PhaseStepper } from "@/components/chat/AgentTimeline";
import { derivePhases } from "@/components/chat/phases";
import { Evidence } from "@/components/chat/Evidence";
import { TestRunCard, VerdictBanner } from "@/components/chat/TestResult";
import { PatchDetail } from "@/components/patches/PatchDetail";

function ErrorCard({ e }: { e: ErrorReport }) {
  return (
    <Card>
      <CardHeader title="What failed" description="Decoded from the error you provided" icon={<Bug className="size-4" />} />
      <CardBody className="space-y-3 text-[13px]">
        <div className="flex flex-wrap items-center gap-2"><Badge variant="destructive" className="font-mono">{e.exception_type || "Error"}</Badge>{e.category && <Badge variant="secondary">{e.category}</Badge>}{e.language && <Badge variant="outline">{e.language}</Badge>}{e.http_status ? <Badge variant="warning">HTTP {e.http_status}</Badge> : null}</div>
        {e.message && <p className="break-words font-mono text-xs">{e.message}</p>}
        {e.file && <div className="rounded-lg bg-surface p-2.5"><FileLink path={e.file} line={e.line} />{e.function && <span className="ml-2 text-xs text-muted-foreground">in {e.function}</span>}{e.code_line && <pre className="mt-1.5 overflow-x-auto font-mono text-[12px]">{e.code_line}</pre>}</div>}
        {e.variables.length > 0 && <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Variables involved</div><ul className="space-y-0.5 text-xs">{e.variables.map((v) => <li key={v.name}><code className="font-mono">{v.name}</code> <span className="text-muted-foreground">{v.evidence}</span></li>)}</ul></div>}
        {e.frames.length > 0 && <div><div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Call stack (this repository)</div><ol className="space-y-0.5">{e.frames.slice(0, 8).map((f, i) => <li key={i} className="flex items-center gap-1.5 text-xs"><span className="w-4 text-right text-muted-foreground">{i + 1}</span><FileLink path={f.file} line={f.line} />{f.func && <span className="text-muted-foreground">{f.func}</span>}</li>)}</ol></div>}
        {e.related_functions.length > 0 && <div className="text-xs text-muted-foreground">Related: {e.related_functions.slice(0, 5).map((r) => `${r.name} (${r.relation})`).join(", ")}</div>}
      </CardBody>
    </Card>
  );
}

function Result({ m, run, repoId }: { m: ChatMessage; run?: import("@/lib/types").Run; repoId: string }) {
  const d = m.result;
  const analysis = (d?.analysis ?? {}) as Record<string, unknown>;
  const root = (analysis.root_cause as string) || "";
  const sources = m.sources ?? [];
  const affected = d?.affected_files ?? [];
  const hasPatch = !!m.patchId;
  return (
    <div className="space-y-4">
      <MockNotice llm={d?.llm} />
      <VerdictBanner v={d?.verification} />
      {d?.error_report && <ErrorCard e={d.error_report} />}
      <Card>
        <CardHeader title="Root cause & explanation" description="Reasoned only from retrieved code. Citations open the exact lines." />
        <CardBody className="space-y-3">
          {root && <div className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-2.5 text-[13px]"><span className="font-medium text-primary">Root cause: </span>{root}</div>}
          <Markdown sources={sources} onCite={() => undefined}>{d?.answer || d?.explanation || "No explanation was produced."}</Markdown>
          <Evidence sources={sources} result={d} run={run} />
        </CardBody>
      </Card>
      {affected.length > 0 && (
        <Card><CardHeader title="Affected files" /><CardBody className="space-y-1.5">{affected.map((f) => <div key={f.path} className="flex flex-wrap items-center gap-2 text-xs"><FileLink path={f.path} />{f.roles.map((r) => <Badge key={r} variant="secondary">{r}</Badge>)}<span className="text-muted-foreground">{f.detail}</span></div>)}</CardBody></Card>
      )}
      {hasPatch ? (
        <Card><CardHeader title={d?.verification?.status === "resolved" ? "Verified fix" : "Suggested fix"} description={d?.verification?.status === "resolved" ? "Verified by a regression test that fails before and passes after." : "Review the diff. This fix has not been proven by tests."} icon={<Wand2 className="size-4" />} actions={<Button asChild size="xs" variant="ghost"><Link href={`/changes?patch=${m.patchId}`}>Open in Changes</Link></Button>} />
          <CardBody><PatchDetail repoId={repoId} patchId={m.patchId!} compact /></CardBody></Card>
      ) : (
        <Card><CardBody><div className="text-[13px] font-medium">{d?.status === "no_fix" || d?.status === "no_change" ? "No fix was proposed" : "No patch is attached"}</div><p className="mt-1 text-xs text-muted-foreground">{d?.explanation && !d.answer ? d.explanation : "The agent didn’t produce a patch for this problem. The explanation above is still grounded in the retrieved code. You can give more context (a stack trace, the failing test) and run it again."}</p></CardBody></Card>
      )}
      {(d?.test_before || d?.test_after) && !hasPatch && <div className="space-y-2"><TestRunCard title="Tests before" run={d?.test_before} /><TestRunCard title="Tests after" run={d?.test_after} /></div>}
      {d?.regression && !hasPatch && <Badge variant={d.regression.failed_before && d.regression.passed_after ? "success" : "warning"}>regression test: {d.regression.failed_before ? "reproduces the bug" : "does not reproduce"} · {d.regression.passed_after ? "passes after" : "fails after"}</Badge>}
    </div>
  );
}

export function DebugPage({ repoId }: { repoId: string }) {
  const { run, stop } = useAgentRun();
  const [text, setText] = useState("");
  const verify = useIde((s) => s.verify), setVerify = useIde((s) => s.setVerify);
  const shots = useIde((s) => s.screenshots), addShot = useIde((s) => s.addScreenshot), removeShot = useIde((s) => s.removeScreenshot);
  const messages = useIde((s) => s.messages);
  const runs = useIde((s) => s.runs);
  const ref = useRef<HTMLTextAreaElement>(null);
  const last = useMemo(() => [...messages].reverse().find((m) => m.role === "assistant" && (m.mode === "debug" || m.mode === "fix")), [messages]);
  const lastRun = runs.find((r) => r.id === last?.runId);
  const running = runs.some((r) => r.state === "running");

  const submit = () => { if (running || (!text.trim() && !shots.length)) return; void run("debug", text.trim()); };
  const onPaste = async (e: React.ClipboardEvent) => {
    const imgs = [...e.clipboardData.files].filter((f) => f.type.startsWith("image/"));
    if (!imgs.length) return;
    e.preventDefault();
    for (const f of imgs.slice(0, 3)) {
      const b64 = await new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] ?? ""); r.onerror = () => rej(r.error); r.readAsDataURL(f); }).catch(() => "");
      if (b64) addShot({ media_type: f.type, data: b64, name: f.name }); else toast.error("Couldn’t read that image");
    }
  };

  return (
    <div className="mx-auto max-w-[1100px] space-y-5 p-4 sm:p-6">
      <PageHeader title="Debugging" description="Paste an error, a stack trace, a failing test or a description. The agent reproduces it, finds the root cause and proposes a fix. A fix is marked verified only when a regression test fails before and passes after." icon={<Bug />} />
      <Card>
        <CardBody className="space-y-3">
          <Textarea ref={ref} value={text} onChange={(e) => setText(e.target.value)} onPaste={onPaste} onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } }} rows={8} aria-label="Error, stack trace or bug description"
            placeholder={"Paste a traceback, log lines or failing test output — or describe the bug.\n\nTraceback (most recent call last):\n  File \"app/handlers.py\", line 42, in create_item\n  ...\nTypeError: unsupported operand type(s) for /: 'int' and 'NoneType'"} className="font-mono text-[12.5px] leading-relaxed" />
          {shots.length > 0 && <div className="flex flex-wrap gap-2">{shots.map((s, i) => <span key={i} className="inline-flex items-center gap-1.5 rounded-md bg-secondary px-2 py-1 text-xs"><ImagePlus className="size-3.5" />{s.name ?? `screenshot ${i + 1}`}<button aria-label="Remove screenshot" onClick={() => removeShot(i)}><X className="size-3.5" /></button></span>)}</div>}
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-muted-foreground"><Switch checked={verify} onCheckedChange={setVerify} label="Verify the fix by running tests" />Verify the fix by running tests</label>
            <span className="hidden text-[11px] text-muted-foreground sm:inline">Paste a screenshot of the error to include it · Ctrl+Enter to run</span>
            <div className="ml-auto flex gap-2">{running ? <Button variant="destructive" onClick={stop}><Square className="fill-current" />Stop</Button> : <Button onClick={submit} disabled={!text.trim() && !shots.length}><Play />Find root cause</Button>}</div>
          </div>
        </CardBody>
      </Card>

      {!last ? <EmptyState icon={<Bug className="size-5" />} title="No investigation yet" description="Results appear here: the decoded error, root cause with citations, affected files, a patch preview with before/after diff and test results, and clear verification status." />
        : last.state === "running" ? (
          <Card><CardBody className="space-y-4" role="status" aria-live="polite"><PhaseStepper phases={derivePhases(lastRun)} /><div className="text-[13px] text-muted-foreground">{currentActivity(lastRun)}</div><Skeleton className="h-24" /></CardBody></Card>
        ) : last.state === "error" ? <ErrorState title="The investigation failed" error={last.error} />
        : last.state === "cancelled" ? <EmptyState title="Stopped" description="The run was stopped before it finished." />
        : <Result m={last} run={lastRun} repoId={repoId} />}
      {last?.state === "done" && lastRun && <div className="flex items-center gap-2 text-xs text-muted-foreground"><FileCode2 className="size-3.5" />Full phases and tool calls are in the <Link className="text-primary hover:underline" href="/chat">AI Chat activity panel</Link>.</div>}
    </div>
  );
}
