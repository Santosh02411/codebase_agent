"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

export const Kbd = ({ children, className }: { children: React.ReactNode; className?: string }) => (
  <kbd className={cn("rounded border bg-secondary px-1.5 py-0.5 font-mono text-[10px] font-medium text-muted-foreground", className)}>{children}</kbd>
);

export function Progress({ value, className, tone = "primary", label }: { value: number; className?: string; tone?: "primary" | "success" | "warning" | "destructive"; label?: string }) {
  const v = Math.max(0, Math.min(100, value));
  const bar = { primary: "bg-primary", success: "bg-success", warning: "bg-warning", destructive: "bg-destructive" }[tone];
  return (
    <div role="progressbar" aria-valuenow={Math.round(v)} aria-valuemin={0} aria-valuemax={100} aria-label={label} className={cn("h-1.5 w-full overflow-hidden rounded-full bg-secondary", className)}>
      <div className={cn("h-full rounded-full transition-[width] duration-500", bar)} style={{ width: `${v}%` }} />
    </div>
  );
}

export function Switch({ checked, onCheckedChange, label, disabled }: { checked: boolean; onCheckedChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onCheckedChange(!checked)}
      className={cn("relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:opacity-50", checked ? "bg-primary" : "bg-input")}>
      <span className={cn("inline-block size-4 rounded-full bg-white shadow transition-transform", checked ? "translate-x-[18px]" : "translate-x-0.5")} />
    </button>
  );
}

export function Segmented<T extends string>({ value, onChange, options, className, size = "md" }: { value: T; onChange: (v: T) => void; options: { value: T; label: React.ReactNode; icon?: React.ReactNode; title?: string }[]; className?: string; size?: "sm" | "md" }) {
  return (
    <div role="tablist" className={cn("inline-flex items-center gap-0.5 rounded-lg bg-secondary p-0.5", className)}>
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={value === o.value} title={o.title} onClick={() => onChange(o.value)}
          className={cn("inline-flex items-center gap-1.5 rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 [&_svg]:size-3.5", size === "sm" ? "h-6 px-2 text-[11px]" : "h-7 px-2.5 text-xs",
            value === o.value ? "bg-panel text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
          {o.icon}{o.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, hint, icon, tone }: { label: string; value: React.ReactNode; hint?: React.ReactNode; icon?: React.ReactNode; tone?: "success" | "warning" | "destructive" }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">{icon}{label}</div>
      <div className={cn("mt-1 text-2xl font-semibold tabular-nums tracking-tight", tone === "success" && "text-success", tone === "warning" && "text-warning", tone === "destructive" && "text-destructive")}>{value}</div>
      {hint && <div className="mt-0.5 truncate text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

export function Table({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("overflow-x-auto", className)}><table className="w-full border-collapse text-left text-[13px]">{children}</table></div>;
}
export const Th = ({ className, ...p }: React.ThHTMLAttributes<HTMLTableCellElement>) => <th className={cn("border-b px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground", className)} {...p} />;
export const Td = ({ className, ...p }: React.TdHTMLAttributes<HTMLTableCellElement>) => <td className={cn("border-b border-border/60 px-3 py-2 align-middle", className)} {...p} />;

export function PageHeader({ title, description, actions, icon }: { title: string; description?: React.ReactNode; actions?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 pb-5">
      <div className="flex min-w-0 items-start gap-3">
        {icon && <div className="mt-0.5 flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary [&_svg]:size-[18px]">{icon}</div>}
        <div className="min-w-0"><h1 className="text-xl font-semibold">{title}</h1>{description && <p className="mt-0.5 max-w-2xl text-[13px] text-muted-foreground">{description}</p>}</div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
