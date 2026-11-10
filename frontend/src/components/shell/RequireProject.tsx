"use client";
import { FolderGit2, Github, Upload } from "lucide-react";
import { motion } from "framer-motion";
import { useCurrentRepo } from "@/hooks/useCurrentRepo";
import { useUi } from "@/lib/ui";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";

const STEPS = [
  { t: "Import", d: "GitHub, URL, ZIP or folder" }, { t: "Index", d: "Parse, chunk, embed" }, { t: "Investigate", d: "Search, read, trace" },
  { t: "Fix", d: "Patch across files" }, { t: "Verify", d: "Tests before / after" },
];

/** Onboarding illustration: the real pipeline, drawn as an animated flow. */
export function WorkflowArt() {
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-1 gap-y-3" aria-hidden>
      {STEPS.map((s, i) => (
        <div key={s.t} className="flex items-center">
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.12 }} className="w-28 rounded-lg bg-panel px-3 py-2.5 text-left shadow-card">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold text-primary"><span className="flex size-4 items-center justify-center rounded-full bg-primary/12 text-[10px]">{i + 1}</span>{s.t}</div>
            <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{s.d}</div>
          </motion.div>
          {i < STEPS.length - 1 && <svg width="22" height="10" viewBox="0 0 22 10" className="text-muted-foreground/50"><path d="M0 5h18m-4-4 4 4-4 4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="3 3"><animate attributeName="stroke-dashoffset" from="12" to="0" dur="1.2s" repeatCount="indefinite" /></path></svg>}
        </div>
      ))}
    </div>
  );
}

export function Onboarding() {
  const setAdd = useUi((s) => s.setAddProject);
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-3xl flex-col items-center justify-center gap-8 px-6 py-12 text-center">
      <div className="space-y-2">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary"><FolderGit2 className="size-6" /></div>
        <h1 className="text-2xl font-semibold">Add a project to get started</h1>
        <p className="mx-auto max-w-lg text-[13px] leading-relaxed text-muted-foreground">Import a repository and the agent will index it, then answer questions about it, review it, trace bugs to their root cause and propose fixes it verifies by running your tests.</p>
      </div>
      <WorkflowArt />
      <div className="flex flex-wrap justify-center gap-2">
        <Button onClick={() => setAdd(true)}><Github /> Import from GitHub or a URL</Button>
        <Button variant="outline" onClick={() => setAdd(true)}><Upload /> Upload a ZIP</Button>
      </div>
    </div>
  );
}

/** Renders children only when a project is selected; otherwise loading, error or onboarding. */
export function RequireProject({ children }: { children: (repoId: string) => React.ReactNode }) {
  const { repoId, isLoading, error, refetch } = useCurrentRepo();
  if (isLoading) return <div className="space-y-4 p-6"><Skeleton className="h-8 w-56" /><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div><Skeleton className="h-64" /></div>;
  if (error) return <div className="mx-auto max-w-xl p-8"><ErrorState title="Can’t load your projects" error={error} onRetry={() => refetch()} /></div>;
  if (!repoId) return <Onboarding />;
  return <>{children(repoId)}</>;
}
