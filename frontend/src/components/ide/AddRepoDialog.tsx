"use client";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderGit2, Github, GitBranch, Link2, Loader2, Lock, LogOut, Upload, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { RemotePreview } from "@/lib/types";
import { useAddRepo, useAuthStatus, useGithubRepos, useHealth } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { ActiveProgress } from "./IndexProgress";

type Kind = "github" | "url" | "zip" | "local";

function BranchPicker({ source, branch, setBranch }: { source: string; branch: string; setBranch: (b: string) => void }) {
  const [info, setInfo] = useState<RemotePreview | null>(null);
  const [error, setError] = useState("");
  const load = useMutation({
    mutationFn: () => api.preview(source),
    onSuccess: (p) => { setInfo(p); setError(""); setBranch(p.default); },
    onError: (e: Error) => { setInfo(null); setError(e.message); },
  });
  useEffect(() => { setInfo(null); setError(""); setBranch(""); }, [source, setBranch]);
  if (!info) {
    return (
      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
        <Button size="xs" variant="outline" disabled={load.isPending || !source} onClick={() => load.mutate()}>{load.isPending ? <Loader2 className="animate-spin" /> : <GitBranch />} Choose branch</Button>
        {error ? <span className="text-destructive">{error}</span> : <span>Default branch is used unless you pick one.</span>}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <GitBranch className="size-3.5 text-muted-foreground" />
      <select value={branch} onChange={(e) => setBranch(e.target.value)} className="h-8 flex-1 rounded-md border border-input bg-background px-2 text-xs">
        {info.branches.map((b) => <option key={b} value={b}>{b}{b === info.default ? "  (default)" : ""}</option>)}
      </select>
      <span className="text-[11px] text-muted-foreground">{info.branches.length} branches</span>
    </div>
  );
}

export function AddRepoDialog({ onClose, initial = "github" }: { onClose: () => void; initial?: Kind }) {
  const add = useAddRepo();
  const health = useHealth();
  const auth = useAuthStatus();
  const qc = useQueryClient();
  const connected = !!auth.data?.github.connected;
  const [kind, setKind] = useState<Kind>(initial);
  const [value, setValue] = useState("");
  const [name, setName] = useState("");
  const [branch, setBranch] = useState("");
  const [query, setQuery] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const repos = useGithubRepos(query, kind === "github" && connected);
  const logout = useMutation({ mutationFn: api.githubLogout, onSuccess: () => { qc.invalidateQueries({ queryKey: ["auth"] }); qc.invalidateQueries({ queryKey: ["ghrepos"] }); setValue(""); } });

  const submit = () => {
    const v = kind === "zip" ? { file: file!, name } : { source: value.trim(), name, branch: branch || undefined };
    add.mutate(v, {
      onSuccess: (repo) => { useIde.getState().setRepoId(repo.id); toast.success(`Indexed ${repo.files} files · ${repo.symbols ?? 0} symbols`); onClose(); },
      onError: (e: Error) => toast.error(e.message),
    });
  };
  const ready = kind === "zip" ? !!file : value.trim().length > 0;
  const Tab = ({ id, icon, label }: { id: Kind; icon: React.ReactNode; label: string }) => (
    <button disabled={add.isPending} onClick={() => { setKind(id); setBranch(""); }} className={cn("flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 [&_svg]:size-3.5", kind === id ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/50")}>{icon}{label}</button>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[10vh]" onMouseDown={(e) => e.target === e.currentTarget && !add.isPending && onClose()}>
      <div className="w-[560px] max-w-[94vw] rounded-xl border bg-panel p-4 shadow-2xl">
        <div className="mb-3 flex items-center"><div className="text-sm font-semibold">Import a repository</div><button className="ml-auto rounded p-1 hover:bg-accent" onClick={onClose} aria-label="Close" disabled={add.isPending}><X className="size-4" /></button></div>
        <div className="mb-3 flex gap-1 rounded-lg bg-background p-1">
          <Tab id="github" icon={<Github />} label="GitHub" /><Tab id="url" icon={<Link2 />} label="Any Git URL" /><Tab id="zip" icon={<Upload />} label="ZIP" />
          {health.data?.allow_local_paths && <Tab id="local" icon={<FolderGit2 />} label="Local" />}
        </div>

        <div className="space-y-2">
          {kind === "github" && !connected && (
            <div className="space-y-3 rounded-lg border p-3">
              <div>Connect your GitHub account to browse and import your repositories, including private ones.</div>
              {auth.data?.github.oauth_configured ? (
                <Button onClick={() => { window.location.href = api.githubLoginUrl(); }}><Github /> Connect GitHub</Button>
              ) : (
                <div className="rounded border border-warning/40 bg-warning/10 p-2 text-[12px]">
                  GitHub sign-in isn’t set up on the server yet. Create an OAuth app at <b>github.com/settings/developers</b> with callback URL <code>http://localhost:8000/auth/github/callback</code>, then set <code>GITHUB_CLIENT_ID</code> and <code>GITHUB_CLIENT_SECRET</code> in <code>.env</code> and restart. Public repositories work right now through <b>Any Git URL</b>.
                </div>
              )}
            </div>
          )}
          {kind === "github" && connected && (
            <>
              <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                {auth.data?.github.user?.avatar && /* eslint-disable-next-line @next/next/no-img-element */ <img src={auth.data.github.user.avatar} alt="" className="size-5 rounded-full" />}
                Connected as <b className="text-foreground">{auth.data?.github.user?.login}</b>
                <button className="ml-auto flex items-center gap-1 hover:text-foreground" onClick={() => logout.mutate()}><LogOut className="size-3" /> Disconnect</button>
              </div>
              <Input placeholder="Search your repositories…" value={query} onChange={(e) => setQuery(e.target.value)} />
              <ScrollArea className="h-52 rounded-md border">
                {repos.isLoading && <div className="p-3 text-muted-foreground">Loading repositories…</div>}
                {repos.error && <div className="p-3 text-destructive">{(repos.error as Error).message}</div>}
                {repos.data?.map((r) => (
                  <button key={r.full_name} onClick={() => { setValue(r.url); setName(r.full_name.split("/")[1]); }} className={cn("flex w-full items-center gap-2 border-b px-3 py-1.5 text-left hover:bg-accent/50", value === r.url && "bg-accent")}>
                    {r.private ? <Lock className="size-3.5 shrink-0 text-warning" /> : <Github className="size-3.5 shrink-0 text-muted-foreground" />}
                    <span className="min-w-0 flex-1"><span className="block truncate font-medium">{r.full_name}</span>{r.description && <span className="block truncate text-[11px] text-muted-foreground">{r.description}</span>}</span>
                    {r.language && <Badge variant="secondary">{r.language}</Badge>}
                  </button>
                ))}
                {repos.data?.length === 0 && <div className="p-3 text-muted-foreground">No repositories match.</div>}
              </ScrollArea>
              {value && <BranchPicker source={value} branch={branch} setBranch={setBranch} />}
            </>
          )}
          {kind === "url" && (
            <>
              <Input autoFocus placeholder="https://github.com/owner/repo · https://gitlab.com/group/project · https://bitbucket.org/owner/repo" value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ready && !add.isPending && submit()} />
              {value.trim() && <BranchPicker source={value.trim()} branch={branch} setBranch={setBranch} />}
              <p className="text-[11px] text-muted-foreground">Public repositories work as-is. For private GitLab/Bitbucket repositories set <code>GITLAB_TOKEN</code> or <code>BITBUCKET_USERNAME</code>/<code>BITBUCKET_APP_PASSWORD</code> in <code>.env</code> (sign-in with GitLab and Bitbucket is planned).</p>
            </>
          )}
          {kind === "local" && <Input autoFocus placeholder="C:\path\to\project  or  /home/me/project" value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ready && !add.isPending && submit()} />}
          {kind === "zip" && (
            <button onClick={() => fileRef.current?.click()} className="flex h-20 w-full flex-col items-center justify-center gap-1 rounded-lg border border-dashed text-muted-foreground hover:bg-accent/40">
              <Upload className="size-5" />{file ? <span className="text-foreground">{file.name}</span> : "Choose a .zip of your project"}
              <input ref={fileRef} type="file" accept=".zip" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </button>
          )}
          <Input placeholder="Display name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        {add.isPending && <div className="mt-3 rounded-lg border bg-background p-3"><ActiveProgress /><div className="mt-1 text-[11px] text-muted-foreground">Large repositories can take a few minutes the first time. Later updates only reprocess changed files.</div></div>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={add.isPending}>Cancel</Button>
          <Button disabled={!ready || add.isPending} onClick={submit}>{add.isPending ? <><Loader2 className="animate-spin" /> Importing…</> : branch ? `Import “${branch}”` : "Import & index"}</Button>
        </div>
      </div>
    </div>
  );
}
