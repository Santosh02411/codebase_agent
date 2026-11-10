"use client";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Github, Monitor, Moon, Settings, Sun, TerminalSquare, XCircle } from "lucide-react";
import { toast } from "sonner";
import { API_URL, api } from "@/lib/api";
import { useAuthStatus, useHealth, useRagInfo } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { useTheme, type ThemePref } from "@/lib/theme";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { PageHeader, Segmented, Switch } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

function Row({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center justify-between gap-3 border-b py-3 last:border-0 first:pt-0 last:pb-0"><div className="min-w-0"><div className="text-[13px] font-medium">{label}</div>{hint && <div className="mt-0.5 max-w-md text-xs text-muted-foreground">{hint}</div>}</div><div className="flex items-center gap-2">{children}</div></div>;
}
const Status = ({ ok, yes, no }: { ok: boolean; yes: string; no: string }) => ok ? <Badge variant="success" className="gap-1"><CheckCircle2 className="size-3" />{yes}</Badge> : <Badge variant="warning" className="gap-1"><CircleAlert className="size-3" />{no}</Badge>;

export function SettingsPage() {
  const health = useHealth();
  const auth = useAuthStatus();
  const rag = useRagInfo();
  const sandbox = useQuery({ queryKey: ["sandbox"], queryFn: api.sandbox, retry: false });
  const usage = useQuery({ queryKey: ["llm-usage"], queryFn: () => fetch(`${API_URL}/llm/usage?recent=0`).then((r) => (r.ok ? r.json() : null)).catch(() => null), retry: false });
  const qc = useQueryClient();
  const pref = useTheme((s) => s.pref), setPref = useTheme((s) => s.setPref);
  const provider = useIde((s) => s.provider), setProvider = useIde((s) => s.setProvider);
  const verify = useIde((s) => s.verify), setVerify = useIde((s) => s.setVerify);
  const logout = useMutation({ mutationFn: api.githubLogout, onSuccess: () => { qc.invalidateQueries({ queryKey: ["auth"] }); toast.success("Disconnected from GitHub"); } });
  const h = health.data;
  const gh = auth.data?.github;
  return (
    <div className="mx-auto max-w-[900px] space-y-4 p-4 sm:p-6">
      <PageHeader title="Settings" description="Appearance, model provider, sandbox and integrations. Keys and tokens live in the backend’s .env file. This page shows what is configured, never the secrets themselves." icon={<Settings />} />
      <Card><CardHeader title="Appearance" /><CardBody>
        <Row label="Theme" hint="System follows your operating system. Both themes are complete palettes, including charts, editors and code blocks."><Segmented value={pref} onChange={(v: ThemePref) => setPref(v)} options={[{ value: "light", label: "Light", icon: <Sun /> }, { value: "dark", label: "Dark", icon: <Moon /> }, { value: "system", label: "System", icon: <Monitor /> }]} /></Row>
      </CardBody></Card>

      <Card><CardHeader title="Model & agent" description="From the backend’s configuration" /><CardBody>
        {health.isLoading ? <Skeleton className="h-24" /> : health.isError ? <p className="text-xs text-destructive">{(health.error as Error).message}</p> : (<>
          <Row label="LLM provider" hint={h?.llm_provider === "mock" ? "The offline mock answers from retrieval only: it can’t analyse root causes or write patches. Set LLM_PROVIDER and a key in .env (see docs/ENV_SETUP.md)." : undefined}><Badge variant={h?.llm_provider === "mock" ? "warning" : "success"}>{h?.llm_provider}</Badge>{h?.llm_model && <code className="font-mono text-xs text-muted-foreground">{h.llm_model}</code>}</Row>
          <Row label="Embeddings" hint="hash = offline and lexical. Real embedding models improve retrieval."><Badge variant="secondary">{h?.embedding_provider}</Badge>{rag.data && <Badge variant="outline">{rag.data.store}</Badge>}{rag.data?.reranker && <Badge variant="outline">rerank: {rag.data.reranker}</Badge>}</Row>
          <Row label="Provider for new runs" hint="Overrides the backend default for runs started from this browser."><Select aria-label="Provider override" className="w-40" value={provider || "default"} onValueChange={(v) => setProvider(v === "default" ? "" : v)} options={[{ value: "default", label: "Backend default" }, { value: "gemini", label: "Gemini" }, { value: "openai", label: "OpenAI" }, { value: "mock", label: "Offline mock" }]} /></Row>
          <Row label="Verify fixes by running tests" hint="Used by Debug, Change and Test modes."><Switch checked={verify} onCheckedChange={setVerify} label="Verify fixes" /></Row>
          {usage.data && typeof usage.data === "object" && "calls" in usage.data && <Row label="Model usage (this server process)"><span className="text-xs tabular-nums text-muted-foreground">{String((usage.data as Record<string, unknown>).calls)} calls · {Number((usage.data as Record<string, unknown>).input_tokens ?? 0).toLocaleString()} in / {Number((usage.data as Record<string, unknown>).output_tokens ?? 0).toLocaleString()} out tokens</span></Row>}
        </>)}
      </CardBody></Card>

      <Card><CardHeader title="Execution sandbox" /><CardBody>
        {sandbox.data ? <Row label={sandbox.data.isolated ? "Docker sandbox" : sandbox.data.mode === "local" ? "Local mode (not isolated)" : "Sandbox unavailable"} hint={sandbox.data.warning ?? sandbox.data.problem ?? "Repository code runs in a locked-down container: no network, read-only filesystem, no privileges."}><Status ok={sandbox.data.isolated} yes="isolated" no={sandbox.data.mode === "local" ? "not isolated" : "unavailable"} /></Row> : <Skeleton className="h-10" />}
      </CardBody></Card>

      <Card><CardHeader title="Integrations" /><CardBody>
        <Row label="GitHub sign-in" hint={gh?.user ? `Connected as @${gh.user.login}` : gh?.oauth_configured ? "Sign in to browse and import private repositories." : "Not configured: set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in .env."}>
          {gh?.user ? <Button size="sm" variant="outline" onClick={() => logout.mutate()} loading={logout.isPending}>Disconnect</Button> : gh?.oauth_configured ? <Button size="sm" onClick={() => { window.location.href = api.githubLoginUrl(); }}><Github />Sign in</Button> : <Status ok={false} yes="" no="not configured" />}</Row>
        <Row label="GitHub token (GITHUB_TOKEN)" hint="Lets the agent read pull requests and issues and open pull requests."><Status ok={!!gh?.token_in_env} yes="set" no="not set" /></Row>
        <Row label="GitLab / Bitbucket tokens" hint="Needed only for private repositories on those hosts."><Status ok={!!auth.data?.gitlab.token_in_env} yes="GitLab set" no="GitLab not set" /><Status ok={!!auth.data?.bitbucket.token_in_env} yes="Bitbucket set" no="Bitbucket not set" /></Row>
        <Row label="Git" hint="Required to import repositories by URL."><Status ok={!!h?.git_available} yes="available" no="not found" /></Row>
        <Row label="Local folders" hint="Importing folders from the server’s disk is off unless ALLOW_LOCAL_PATHS=true."><Status ok={!!h?.allow_local_paths} yes="allowed" no="disabled" /></Row>
        <p className="pt-3 text-xs text-muted-foreground">How to get every key, and what happens when one is missing: <code className="rounded bg-secondary px-1 font-mono">docs/ENV_SETUP.md</code> in the repository.</p>
      </CardBody></Card>

      <Card><CardHeader title="Connection & tools" /><CardBody>
        <Row label="Backend API"><code className="font-mono text-xs">{API_URL || "same origin (this server)"}</code>{h ? <Badge variant="success">connected</Badge> : <XCircle className="size-4 text-destructive" />}</Row>
        <Row label="IDE view" hint="The original multi-tab IDE layout, with terminal, git panel and retrieval experiments."><Button asChild size="sm" variant="outline"><Link href="/workbench"><TerminalSquare />Open IDE view</Link></Button></Row>
      </CardBody></Card>
    </div>
  );
}
