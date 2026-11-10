"use client";
import { Suspense } from "react";
import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { FileDiff } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { ago } from "@/components/shell/IndexStatus";
import { PatchDetail } from "./PatchDetail";

function ChangesPageInner({ repoId }: { repoId: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const sel = params.get("patch");
  const list = useQuery({ queryKey: ["patches", repoId], queryFn: () => api.patches(repoId), refetchInterval: 15_000 });
  const items = [...(list.data ?? [])].sort((a, b) => b.created - a.created);
  useEffect(() => { if (!sel && items.length) router.replace(`/changes?patch=${items[0].id}`); }, [sel, items, router]);
  return (
    <div className="mx-auto max-w-[1320px] p-4 sm:p-6">
      <PageHeader title="Changes & Patches" description="Every change the agent proposes is stored here with its exact diff and verification. Nothing touches your project until you approve it." icon={<FileDiff />} />
      {list.isLoading ? <div className="grid gap-4 lg:grid-cols-[280px_1fr]"><Skeleton className="h-64" /><Skeleton className="h-96" /></div>
        : list.isError ? <ErrorState title="Couldn’t load patches" error={list.error} onRetry={() => list.refetch()} />
        : items.length === 0 ? <EmptyState icon={<FileDiff className="size-5" />} title="No patches yet" description="When the agent proposes a fix or a change, it appears here for review. Try the Debug or Change mode." action={<div className="flex gap-2"><Button asChild size="sm"><Link href="/debug">Debug an error</Link></Button><Button asChild size="sm" variant="outline"><Link href="/chat">Open chat</Link></Button></div>} />
        : (
          <div className="grid items-start gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
            <ul className="space-y-1.5 lg:sticky lg:top-4" aria-label="Patches">
              {items.map((p) => (
                <li key={p.id}><button onClick={() => router.push(`/changes?patch=${p.id}`)} aria-current={sel === p.id} className={cn("w-full rounded-xl bg-panel p-3 text-left shadow-card transition-colors hover:bg-accent/50", sel === p.id && "ring-2 ring-primary/40")}>
                  <div className="flex items-center gap-2"><Badge variant={p.status === "applied" ? "success" : p.status === "proposed" ? "warning" : "secondary"}>{p.status}</Badge><span className="ml-auto text-[11px] text-muted-foreground">{ago(p.created)}</span></div>
                  <div className="mt-1.5 line-clamp-2 text-[13px] font-medium">{p.title}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{p.stats.files} file(s) · <span className="text-success">+{p.stats.additions}</span> <span className="text-destructive">−{p.stats.deletions}</span>{p.origin?.intent ? ` · ${p.origin.intent}` : ""}</div></button></li>
              ))}
            </ul>
            <div className="min-w-0 rounded-xl bg-surface/40">{sel ? <PatchDetail key={sel} repoId={repoId} patchId={sel} /> : null}</div>
          </div>
        )}
    </div>
  );
}

/** useSearchParams needs a Suspense boundary; it lives INSIDE the project check so the server HTML and the first client render agree. */
export function ChangesPage({ repoId }: { repoId: string }) {
  return <Suspense fallback={null}><ChangesPageInner repoId={repoId} /></Suspense>;
}
