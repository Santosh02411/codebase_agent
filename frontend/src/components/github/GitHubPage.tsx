"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bug, CircleDot, Eye, GitBranch, GitPullRequest, Github, RefreshCw, Search, Send } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useIde } from "@/store/ide";
import { useUi } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { GhPull, PRReport, ResultData } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Drawer } from "@/components/ui/dialog";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Input, Textarea } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FileLink, SeverityBadge } from "@/components/common/bits";
import { Markdown } from "@/components/common/Markdown";
import { ApprovalCard, usePendingActions } from "@/components/ide/Approvals";
import { ago } from "@/components/shell/IndexStatus";

const EVENT = { approve: "APPROVE", comment: "COMMENT", request_changes: "REQUEST_CHANGES" } as const;

function NotConfigured({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error ?? "");
  const setAdd = useUi((s) => s.setAddProject);
  if (/not a github repository/i.test(msg)) {
    return (
      <EmptyState className="mx-auto max-w-xl" icon={<GitPullRequest className="size-5" />} title="This project isn’t connected to GitHub"
        description="It was imported from a ZIP or a folder, so it has no GitHub remote to read pull requests or issues from. Import it from its GitHub URL (or pick it from your GitHub repositories) to review pull requests, fix issues and push changes from here."
        action={<Button onClick={() => setAdd(true)}><Github />Import from GitHub</Button>} />
    );
  }
  if (/not connected|token|sign in/i.test(msg)) {
    return (
      <EmptyState className="mx-auto max-w-xl" icon={<GitPullRequest className="size-5" />} title="GitHub access isn’t set up"
        description="Sign in with GitHub (profile menu, top right) or set GITHUB_TOKEN in .env, then refresh. Importing public repositories and everything else in the app works without it."
        action={<Button asChild variant="outline"><Link href="/settings">Open Settings</Link></Button>} />
    );
  }
  return <ErrorState title="GitHub isn’t available for this project" error={error} className="mx-auto max-w-xl" />;
}

function ReportView({ repoId, rep, onProposed }: { repoId: string; rep: PRReport; onProposed: () => void }) {
  const [pick, setPick] = useState<Set<number>>(new Set((rep.comments ?? []).map((_, i) => i)));
  const [body, setBody] = useState(rep.summary);
  const [event, setEvent] = useState<keyof typeof EVENT>(rep.verdict ?? "comment");
  const propose = useMutation({
    mutationFn: () => api.proposeReview(repoId, rep.number, body, EVENT[event], (rep.comments ?? []).filter((_, i) => pick.has(i)).map((c) => ({ path: c.path, line: c.line, body: c.body, severity: c.severity }))),
    onSuccess: () => { toast.success("Review drafted. Approve it in the Approvals tab to post it."); onProposed(); },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <div className="space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-2"><Badge variant="secondary" className="capitalize">{rep.kind}</Badge>{rep.risk && <Badge variant={rep.risk === "high" ? "destructive" : rep.risk === "medium" ? "warning" : "success"}>{rep.risk} risk</Badge>}{rep.change_type && <Badge variant="outline">{rep.change_type}</Badge>}{rep.verdict && <Badge variant="info">suggests: {rep.verdict.replace("_", " ")}</Badge>}</div>
      <Markdown>{rep.summary}</Markdown>
      {rep.static_note && <p className="text-xs text-muted-foreground">{rep.static_note}</p>}
      {(rep.concerns ?? []).length > 0 && <div><div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Concerns</div><ul className="space-y-1.5">{rep.concerns!.map((c, i) => <li key={i} className="flex items-start gap-2 text-[13px]"><SeverityBadge s={c.severity} /><span className="min-w-0"><FileLink path={c.file} line={c.line} /><span className="block text-xs text-muted-foreground">{c.message}</span></span></li>)}</ul></div>}
      {rep.kind === "review" && (
        <div className="space-y-3 border-t pt-4">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Draft inline comments ({pick.size}/{(rep.comments ?? []).length} selected)</div>
          {(rep.comments ?? []).length === 0 ? <p className="text-xs text-muted-foreground">No inline comments in this draft.</p> : <ul className="space-y-2">{rep.comments!.map((c, i) => (
            <li key={i} className="flex items-start gap-2.5 rounded-lg bg-surface/60 p-2.5"><input type="checkbox" aria-label={`Include comment on ${c.path}:${c.line}`} checked={pick.has(i)} onChange={() => setPick((s) => { const n = new Set(s); if (n.has(i)) n.delete(i); else n.add(i); return n; })} className="mt-1 accent-[hsl(var(--primary))]" />
              <div className="min-w-0 text-[13px]"><div className="flex items-center gap-2"><SeverityBadge s={c.severity} /><span className="font-mono text-[11px] text-muted-foreground">{c.path}:{c.line}</span>{c.source && <Badge variant="outline">{c.source}</Badge>}</div><p className="mt-1">{c.body}</p></div></li>))}</ul>}
          <Textarea value={body} onChange={(e) => setBody(e.target.value)} rows={4} aria-label="Review summary" />
          <div className="flex flex-wrap items-center gap-2"><select aria-label="Review verdict" value={event} onChange={(e) => setEvent(e.target.value as keyof typeof EVENT)} className="h-8 rounded-md border bg-panel px-2 text-[13px]"><option value="comment">Comment</option><option value="approve">Approve</option><option value="request_changes">Request changes</option></select>
            <Button onClick={() => propose.mutate()} loading={propose.isPending}><Send />Propose posting this review</Button><span className="text-[11px] text-muted-foreground">Nothing is posted until you approve it in the Approvals tab.</span></div>
        </div>
      )}
    </div>
  );
}

export function GitHubPage({ repoId }: { repoId: string }) {
  const qc = useQueryClient();
  const provider = useIde((s) => s.provider);
  const [tab, setTab] = useState("prs");
  const [busy, setBusy] = useState<string | null>(null);
  const [report, setReport] = useState<PRReport | null>(null);
  const pulls = useQuery({ queryKey: ["ghpulls", repoId], queryFn: () => api.ghPulls(repoId), retry: false });
  const issues = useQuery({ queryKey: ["ghissues", repoId], queryFn: () => api.ghIssues(repoId), retry: false, enabled: tab === "issues" });
  const summary = useQuery({ queryKey: ["gitsummary", repoId], queryFn: () => api.gitSummary(repoId), retry: false, enabled: tab === "repo" });
  const actions = usePendingActions(repoId);
  const pending = (actions.data ?? []).filter((a) => a.status === "pending");
  const seen = useRef(0);
  useEffect(() => { if (pending.length > seen.current) setTab("approvals"); seen.current = pending.length; }, [pending.length]);

  const work = async (key: string, fn: () => Promise<ResultData>, mode: "review" | "debug", label: string) => {
    setBusy(key);
    try {
      const d = await fn();
      if (d.pr_report) setReport(d.pr_report);
      if (d.patch_id) { useIde.getState().addMessage({ id: Math.random().toString(36).slice(2), role: "assistant", mode, text: label, state: "done", result: d, sources: d.sources, patchId: d.patch_id, ts: Date.now() }); toast.success("A patch is ready in Changes & Patches. Nothing has been changed yet."); }
      else if (!d.pr_report) toast.message("Done, but the agent returned no report.");
    } catch (e) { toast.error((e as Error).message); } finally { setBusy(null); }
  };

  const [pushBranch, setPushBranch] = useState("");
  const push = useMutation({ mutationFn: () => api.proposePush(repoId, pushBranch || undefined), onSuccess: () => { toast.success("Push proposed. Review it in Approvals."); qc.invalidateQueries({ queryKey: ["actions", repoId] }); }, onError: (e: Error) => toast.error(e.message) });

  const err = pulls.error;
  return (
    <div className="mx-auto max-w-[1100px] space-y-4 p-4 sm:p-6">
      <PageHeader title="GitHub & Pull Requests" description="Analyze and review pull requests, fix issues, and prepare pushes. Anything visible outside this machine is shown in full and needs your approval first." icon={<GitPullRequest />}
        actions={<Button variant="outline" size="sm" onClick={() => { pulls.refetch(); actions.refetch(); }}><RefreshCw className={cn(pulls.isFetching && "animate-spin")} />Refresh</Button>} />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="border-b"><TabsTrigger value="prs">Pull requests {pulls.data && <span className="tabular-nums text-muted-foreground">{pulls.data.length}</span>}</TabsTrigger><TabsTrigger value="issues">Issues</TabsTrigger><TabsTrigger value="approvals">Approvals {pending.length > 0 && <Badge variant="warning">{pending.length}</Badge>}</TabsTrigger><TabsTrigger value="repo">Repository</TabsTrigger></TabsList>
        <TabsContent value="prs" className="pt-4 space-y-2.5">
          {pulls.isLoading ? <Skeleton className="h-32" /> : err ? <NotConfigured error={err} /> : (pulls.data ?? []).length === 0 ? <EmptyState icon={<GitPullRequest className="size-5" />} title="No open pull requests" /> : (pulls.data ?? []).map((p: GhPull) => (
            <Card key={p.number}><CardBody className="space-y-2.5">
              <div className="flex items-start gap-2.5"><GitPullRequest className="mt-0.5 size-4 shrink-0 text-success" /><div className="min-w-0 flex-1"><a href={p.url} target="_blank" rel="noreferrer" className="text-[13px] font-medium hover:underline"><span className="text-muted-foreground">#{p.number}</span> {p.title}</a><div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">{p.author} · <span className="inline-flex items-center gap-1 font-mono"><GitBranch className="size-3" />{p.head} → {p.base}</span> · {ago(p.updated_at)}{p.draft && <Badge variant="secondary">draft</Badge>}{p.labels.map((l) => <Badge key={l} variant="outline">{l}</Badge>)}</div></div></div>
              <div className="flex gap-2"><Button size="sm" variant="outline" loading={busy === `a${p.number}`} disabled={busy !== null} onClick={() => void work(`a${p.number}`, () => api.ghAnalyze(repoId, p.number, provider), "review", `Analyze PR #${p.number}`)}><Search />Analyze</Button><Button size="sm" variant="outline" loading={busy === `r${p.number}`} disabled={busy !== null} onClick={() => void work(`r${p.number}`, () => api.ghReview(repoId, p.number, provider), "review", `Review PR #${p.number}`)}><Eye />Draft a review</Button></div>
            </CardBody></Card>
          ))}
        </TabsContent>
        <TabsContent value="issues" className="pt-4 space-y-2.5">
          {issues.isLoading ? <Skeleton className="h-32" /> : issues.error ? <NotConfigured error={issues.error} /> : (issues.data ?? []).length === 0 ? <EmptyState icon={<CircleDot className="size-5" />} title="No open issues" /> : (issues.data ?? []).map((i) => (
            <Card key={i.number}><CardBody className="space-y-2.5"><div className="flex items-start gap-2.5"><CircleDot className="mt-0.5 size-4 shrink-0 text-warning" /><div className="min-w-0 flex-1"><a href={i.url} target="_blank" rel="noreferrer" className="text-[13px] font-medium hover:underline"><span className="text-muted-foreground">#{i.number}</span> {i.title}</a><div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">{i.author} · {i.comments} comment(s) · {ago(i.updated_at)}{i.labels.map((l) => <Badge key={l} variant="outline">{l}</Badge>)}</div></div></div>
              <Button size="sm" loading={busy === `i${i.number}`} disabled={busy !== null} onClick={() => void work(`i${i.number}`, () => api.ghFixIssue(repoId, i.number, provider), "debug", `Fix issue #${i.number}`)}><Bug />Fix this issue</Button></CardBody></Card>
          ))}
        </TabsContent>
        <TabsContent value="approvals" className="pt-4 space-y-3">
          {(actions.data ?? []).length === 0 ? <EmptyState title="Nothing waiting for approval" description="Pushes, pull requests and posted reviews appear here with their full content, and only happen when you approve them." /> : (actions.data ?? []).map((a) => <ApprovalCard key={a.id} a={a} repoId={repoId} />)}
        </TabsContent>
        <TabsContent value="repo" className="pt-4">
          {summary.isLoading ? <Skeleton className="h-40" /> : summary.error ? <NotConfigured error={summary.error} /> : summary.data && (
            <div className="grid gap-4 md:grid-cols-2">
              <Card><CardHeader title="Branches & remotes" /><CardBody className="space-y-2 text-[13px]"><div>Current: <Badge variant="secondary" className="font-mono">{summary.data.current}</Badge> <span className="font-mono text-xs text-muted-foreground">{summary.data.commit.slice(0, 8)}</span></div><div className="text-xs text-muted-foreground">Default: {summary.data.default} · {summary.data.branches.length} branches</div>{summary.data.remotes.map((r) => <div key={r.name} className="truncate font-mono text-xs text-muted-foreground">{r.name} {r.url}</div>)}
                <div className="flex gap-2 pt-2"><Input value={pushBranch} onChange={(e) => setPushBranch(e.target.value)} placeholder={`Branch to push (default ${summary.data.current})`} aria-label="Branch to push" /><Button variant="outline" loading={push.isPending} onClick={() => push.mutate()}>Propose push</Button></div></CardBody></Card>
              <Card><CardHeader title="Recent commits" /><CardBody className="space-y-1">{summary.data.recent.map((c) => <div key={c.short} className="flex gap-2 text-[13px]"><code className="font-mono text-xs text-muted-foreground">{c.short}</code><span className="min-w-0 flex-1 truncate">{c.subject}</span><span className="text-xs text-muted-foreground">{c.author}</span></div>)}</CardBody></Card>
            </div>
          )}
          <p className="mt-4 text-xs text-muted-foreground">Need to sign in or set a token? See <Link href="/settings" className="text-primary hover:underline">Settings → Integrations</Link>.</p>
        </TabsContent>
      </Tabs>
      <Drawer open={!!report} onOpenChange={(o) => !o && setReport(null)} title={report ? `${report.kind === "review" ? "Review draft" : "Analysis"} · PR #${report.number}` : ""} description="Generated by the agent from the diff. Treat it as a draft." width="max-w-xl">
        {report && <ReportView repoId={repoId} rep={report} onProposed={() => { setReport(null); setTab("approvals"); qc.invalidateQueries({ queryKey: ["actions", repoId] }); }} />}
      </Drawer>
    </div>
  );
}
