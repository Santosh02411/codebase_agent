"use client";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { Box, Boxes, Database, FileCode2, FlaskConical, FolderTree, GitFork, Layers, Loader2, Sparkles, Waypoints, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import { useOpenFile } from "@/hooks/useOpen";
import { parseLines } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { useState } from "react";
import { Markdown } from "@/components/common/Markdown";
import { System3D } from "@/components/arch3d/System3D";
import { SystemMap } from "@/components/diagrams/SystemMap";
import { ExecutionFlow } from "@/components/diagrams/ExecutionFlow";
import { StructureTree } from "@/components/diagrams/StructureTree";
import { ArchitecturePage } from "./ArchitecturePage";
import { FolderGraph, ModelsView, TestMap } from "./Perspectives";

const PERSPECTIVES = [
  { id: "map", label: "System map", icon: Layers, hint: "Components grouped by role, with labelled arrows" },
  { id: "execution", label: "Execution flow", icon: Workflow, hint: "Sequence diagram and flowchart of what runs when a function or route is called" },
  { id: "structure", label: "File structure", icon: FolderTree, hint: "The project tree annotated with entry points, tests and usage" },
  { id: "system", label: "3D map", icon: Box, hint: "The whole repository as a navigable 3D map" },
  { id: "folders", label: "Folders", icon: Boxes, hint: "Folder-level dependencies" },
  { id: "files", label: "Files", icon: FileCode2, hint: "File import graph" },
  { id: "calls", label: "Function calls", icon: GitFork, hint: "Who calls what" },
  { id: "models", label: "Data models", icon: Database, hint: "ORM and schema models" },
  { id: "tests", label: "Tests ↔ source", icon: FlaskConical, hint: "Which tests exercise which modules" },
  { id: "impact", label: "Impact", icon: Waypoints, hint: "What breaks if a file changes" },
] as const;

function Body({ repoId }: { repoId: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const openFile = useOpenFile();
  const p = (params.get("p") as (typeof PERSPECTIVES)[number]["id"]) || "map";
  const [open, setOpen] = useState(false);
  const explain = useMutation({ mutationFn: () => api.explain(repoId, "architecture", [], []) });
  const res = explain.data;
  const go = (id: string) => { const q = new URLSearchParams(params.toString()); q.set("p", id); router.replace(`/architecture?${q.toString()}`); };
  const current = PERSPECTIVES.find((x) => x.id === p) ?? PERSPECTIVES[0];
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
        <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto" role="tablist" aria-label="Architecture perspectives">
          {PERSPECTIVES.map((x) => (
            <button key={x.id} role="tab" aria-selected={p === x.id} title={x.hint} onClick={() => go(x.id)} className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 ${p === x.id ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground"}`}><x.icon className="size-3.5" />{x.label}</button>
          ))}
        </div>
        <Button size="sm" onClick={() => { setOpen(true); if (!explain.data && !explain.isPending) explain.mutate(); }}><Sparkles />Explain this architecture</Button>
      </div>
      <div className="min-h-0 flex-1" key={p}>
        {p === "map" && <SystemMap repoId={repoId} />}
        {p === "execution" && <ExecutionFlow repoId={repoId} />}
        {p === "structure" && <StructureTree repoId={repoId} />}
        {p === "system" && <System3D repoId={repoId} />}
        {p === "folders" && <FolderGraph repoId={repoId} />}
        {p === "files" && <ArchitecturePage repoId={repoId} fixedView="modules" />}
        {p === "calls" && <ArchitecturePage repoId={repoId} fixedView="calls" />}
        {p === "models" && <ModelsView repoId={repoId} />}
        {p === "tests" && <TestMap repoId={repoId} />}
        {p === "impact" && <ArchitecturePage repoId={repoId} fixedView="impact" />}
      </div>
      <Drawer open={open} onOpenChange={setOpen} title="Architecture explained" description={`AI explanation, grounded in the parsed relationships and retrieved code. Perspective: ${current.label}`} width="max-w-xl">
        <div className="space-y-3 p-5">
          {explain.isPending ? <div className="flex items-center gap-2 text-[13px] text-muted-foreground"><Loader2 className="size-4 animate-spin" />Reading the code and the graph…</div>
            : explain.isError ? <p className="text-sm text-destructive">{(explain.error as Error).message}</p>
            : res?.state === "unavailable" ? <div className="rounded-lg border border-warning/30 bg-warning/8 p-3 text-[13px]"><div className="font-medium text-warning">Offline mode: no AI explanation</div><p className="mt-1 text-muted-foreground">{res.reason}</p><p className="mt-2 text-xs text-muted-foreground">The graphs themselves are real and parser-derived; only the written explanation needs a model.</p></div>
            : res ? <><Markdown sources={res.sources} onCite={(n) => { const s = res.sources?.find((x) => x.cite === n); if (s) openFile(s.file, parseLines(s.lines)[0]); }}>{res.answer ?? ""}</Markdown><div className="text-[11px] text-muted-foreground">{res.llm} · {res.sources?.length ?? 0} snippets retrieved</div><Button size="xs" variant="outline" onClick={() => explain.mutate()}>Regenerate</Button></> : null}
        </div>
      </Drawer>
    </div>
  );
}

export function ArchHub({ repoId }: { repoId: string }) { return <Suspense fallback={null}><Body repoId={repoId} /></Suspense>; }
