"use client";
import * as React from "react";
import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import { Button } from "./button";
import { cn } from "@/lib/utils";

export function EmptyState({ icon, title, description, action, className, art }: { icon?: React.ReactNode; title: string; description?: React.ReactNode; action?: React.ReactNode; className?: string; art?: React.ReactNode }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-6 py-12 text-center", className)}>
      {art ?? <div className="flex size-11 items-center justify-center rounded-xl bg-secondary text-muted-foreground">{icon ?? <Inbox className="size-5" />}</div>}
      <div className="space-y-1"><div className="text-sm font-medium">{title}</div>{description && <div className="mx-auto max-w-sm text-xs leading-relaxed text-muted-foreground">{description}</div>}</div>
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Something went wrong", className }: { error?: unknown; onRetry?: () => void; title?: string; className?: string }) {
  const msg = error instanceof Error ? error.message : typeof error === "string" ? error : "Unknown error";
  return (
    <div role="alert" className={cn("flex flex-col items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-6 py-8 text-center", className)}>
      <AlertTriangle className="size-5 text-destructive" />
      <div className="space-y-1"><div className="text-sm font-medium">{title}</div><div className="mx-auto max-w-md break-words text-xs text-muted-foreground">{msg}</div></div>
      {onRetry && <Button size="sm" variant="outline" onClick={onRetry}><RefreshCw /> Try again</Button>}
    </div>
  );
}
