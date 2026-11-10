"use client";
import * as React from "react";
import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

const overlay = "fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0";

export function DialogContent({ className, children, title, description, hideClose, ...p }: React.ComponentPropsWithoutRef<typeof D.Content> & { title: string; description?: string; hideClose?: boolean }) {
  return (
    <D.Portal>
      <D.Overlay className={overlay} />
      <D.Content
        className={cn("fixed left-1/2 top-1/2 z-50 max-h-[88vh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-xl bg-panel shadow-pop focus:outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95", className)}
        {...p}
      >
        <D.Title className="sr-only">{title}</D.Title>
        <D.Description className="sr-only">{description ?? title}</D.Description>
        {children}
        {!hideClose && <D.Close className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Close"><X className="size-4" /></D.Close>}
      </D.Content>
    </D.Portal>
  );
}

/** Right-hand drawer (details of a finding, a run, a file...). */
export function Drawer({ open, onOpenChange, title, description, children, width = "max-w-md" }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string; children: React.ReactNode; width?: string }) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className={overlay} />
        <D.Content className={cn("fixed inset-y-0 right-0 z-50 flex w-full flex-col bg-panel shadow-pop focus:outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right", width)}>
          <div className="flex items-start justify-between gap-3 border-b px-5 py-4">
            <div className="min-w-0"><D.Title className="truncate text-sm font-semibold">{title}</D.Title><D.Description className="mt-0.5 text-xs text-muted-foreground">{description ?? " "}</D.Description></div>
            <D.Close className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Close"><X className="size-4" /></D.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
