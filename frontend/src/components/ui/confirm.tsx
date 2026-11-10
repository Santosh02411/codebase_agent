"use client";
import { Dialog, DialogClose, DialogContent } from "./dialog";
import { Button } from "./button";

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel = "Confirm", tone = "default", onConfirm, loading }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; description: React.ReactNode; confirmLabel?: string; tone?: "default" | "destructive"; onConfirm: () => void; loading?: boolean }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={title} description={typeof description === "string" ? description : title}>
        <div className="space-y-3 p-5">
          <h2 className="pr-6 text-sm font-semibold">{title}</h2>
          <div className="text-xs leading-relaxed text-muted-foreground">{description}</div>
          <div className="flex justify-end gap-2"><DialogClose asChild><Button variant="outline" size="sm">Cancel</Button></DialogClose><Button size="sm" variant={tone === "destructive" ? "destructive" : "default"} loading={loading} onClick={onConfirm}>{confirmLabel}</Button></div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
