"use client";
import Link from "next/link";
import { Bell, CircleAlert, GitPullRequest, Loader2, ServerCrash, TriangleAlert } from "lucide-react";
import { useActiveIndexing, useHealth } from "@/hooks/queries";
import { useCurrentRepo } from "@/hooks/useCurrentRepo";
import { usePendingActions } from "@/components/ide/Approvals";
import { useIde } from "@/store/ide";
import { Button } from "@/components/ui/button";
import { Dropdown, DropdownContent, DropdownLabel, DropdownTrigger } from "@/components/ui/dropdown";

interface Item { key: string; icon: React.ReactNode; title: string; detail?: string; href?: string; tone?: "warn" | "bad" | "info" }

/** Only real, current conditions: pending approvals, a running or failed agent run, an indexing problem, an unreachable API. */
export function Notifications() {
  const { repoId } = useCurrentRepo();
  const health = useHealth();
  const actions = usePendingActions(repoId);
  const active = useActiveIndexing(!!repoId);
  const runs = useIde((s) => s.runs);
  const items: Item[] = [];
  if (health.isError) items.push({ key: "api", icon: <ServerCrash className="size-4 text-destructive" />, title: "Backend unreachable", detail: (health.error as Error).message, tone: "bad", href: "/settings" });
  const pending = (actions.data ?? []).filter((a) => a.status === "pending");
  if (pending.length) items.push({ key: "appr", icon: <GitPullRequest className="size-4 text-warning" />, title: `${pending.length} action${pending.length > 1 ? "s" : ""} waiting for your approval`, detail: pending[0].preview.title, href: "/github", tone: "warn" });
  const running = runs.find((r) => r.state === "running");
  if (running) items.push({ key: "run", icon: <Loader2 className="size-4 animate-spin text-info" />, title: "Agent is working", detail: running.label, href: "/chat", tone: "info" });
  const failed = [...runs].reverse().find((r) => r.state === "error");
  if (failed) items.push({ key: "fail", icon: <CircleAlert className="size-4 text-destructive" />, title: "Last agent run failed", detail: failed.label, href: "/chat", tone: "bad" });
  if (repoId && active.data?.[repoId]?.state === "error") items.push({ key: "idx", icon: <TriangleAlert className="size-4 text-destructive" />, title: "Indexing failed", detail: active.data[repoId].error, tone: "bad" });
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label={`Notifications${items.length ? ` (${items.length})` : ""}`}>
          <Bell />
          {items.length > 0 && <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-primary ring-2 ring-background" />}
        </Button>
      </DropdownTrigger>
      <DropdownContent className="w-80 p-0">
        <DropdownLabel className="border-b px-3">Notifications</DropdownLabel>
        {items.length === 0 ? <div className="px-3 py-6 text-center text-xs text-muted-foreground">You’re all caught up.</div> : (
          <ul className="max-h-80 divide-y overflow-y-auto">
            {items.map((i) => {
              const body = <div className="flex gap-2.5 px-3 py-2.5 hover:bg-accent"><span className="mt-0.5">{i.icon}</span><span className="min-w-0"><span className="block text-[13px] font-medium">{i.title}</span>{i.detail && <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">{i.detail}</span>}</span></div>;
              return <li key={i.key}>{i.href ? <Link href={i.href}>{body}</Link> : body}</li>;
            })}
          </ul>
        )}
      </DropdownContent>
    </Dropdown>
  );
}
