"use client";
import { useRef, useState } from "react";
import { FolderGit2, Github, Loader2, Upload, X } from "lucide-react";
import { toast } from "sonner";
import { useAddRepo, useHealth } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export function AddRepoDialog({ onClose }: { onClose: () => void }) {
  const add = useAddRepo();
  const health = useHealth();
  const [kind, setKind] = useState<"github" | "zip" | "local">("github");
  const [value, setValue] = useState("");
  const [name, setName] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);

  const submit = () => {
    const v = kind === "zip" ? { file: file!, name } : { source: value.trim(), name };
    add.mutate(v, {
      onSuccess: (repo) => { useIde.getState().setRepoId(repo.id); toast.success(`Indexed ${repo.files} files into ${repo.chunks} searchable pieces`); onClose(); },
      onError: (e: Error) => toast.error(e.message),
    });
  };
  const ready = kind === "zip" ? !!file : value.trim().length > 0;
  const Tab = ({ id, icon, label }: { id: typeof kind; icon: React.ReactNode; label: string }) => (
    <button onClick={() => setKind(id)} className={cn("flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 [&_svg]:size-3.5", kind === id ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/50")}>{icon}{label}</button>
  );
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[14vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="w-[520px] max-w-[92vw] rounded-xl border bg-panel p-4 shadow-2xl">
        <div className="mb-3 flex items-center"><div className="text-sm font-semibold">Add a repository</div><button className="ml-auto rounded p-1 hover:bg-accent" onClick={onClose} aria-label="Close"><X className="size-4" /></button></div>
        <div className="mb-3 flex gap-1 rounded-lg bg-background p-1">
          <Tab id="github" icon={<Github />} label="GitHub URL" /><Tab id="zip" icon={<Upload />} label="Upload ZIP" />
          {health.data?.allow_local_paths && <Tab id="local" icon={<FolderGit2 />} label="Local folder" />}
        </div>
        <div className="space-y-2">
          {kind === "github" && <Input autoFocus placeholder="https://github.com/owner/repo" value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ready && submit()} />}
          {kind === "local" && <Input autoFocus placeholder="C:\path\to\project  or  /home/me/project" value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ready && submit()} />}
          {kind === "zip" && (
            <button onClick={() => fileRef.current?.click()} className="flex h-20 w-full flex-col items-center justify-center gap-1 rounded-lg border border-dashed text-muted-foreground hover:bg-accent/40">
              <Upload className="size-5" />{file ? <span className="text-foreground">{file.name}</span> : "Choose a .zip of your project"}
              <input ref={fileRef} type="file" accept=".zip" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </button>
          )}
          <Input placeholder="Display name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
          <p className="text-[11px] text-muted-foreground">
            {kind === "github" ? "Public repositories are cloned with `git clone --depth 1`." : kind === "zip" ? "Virtual environments and node_modules are skipped automatically." : "Enabled because the server runs with ALLOW_LOCAL_PATHS=true. The folder is copied; your original is never modified."}
          </p>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={!ready || add.isPending} onClick={submit}>{add.isPending ? <><Loader2 className="animate-spin" /> Indexing…</> : "Add & index"}</Button>
        </div>
      </div>
    </div>
  );
}
