"use client";
import * as React from "react";
import * as M from "@radix-ui/react-dropdown-menu";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export function Dropdown(props: React.ComponentProps<typeof M.Root>) { return <M.Root modal={false} {...props} />; }
export const DropdownTrigger = M.Trigger;
export const DropdownLabel = ({ className, ...p }: React.ComponentPropsWithoutRef<typeof M.Label>) => <M.Label className={cn("px-2 py-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground", className)} {...p} />;
export const DropdownSeparator = () => <M.Separator className="-mx-1 my-1 h-px bg-border" />;

export function DropdownContent({ className, align = "end", ...p }: React.ComponentPropsWithoutRef<typeof M.Content>) {
  return (
    <M.Portal>
      <M.Content align={align} sideOffset={6} className={cn("z-50 min-w-[11rem] overflow-hidden rounded-lg bg-panel p-1 text-[13px] shadow-pop data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95", className)} {...p} />
    </M.Portal>
  );
}

export function DropdownItem({ className, checked, icon, children, ...p }: React.ComponentPropsWithoutRef<typeof M.Item> & { checked?: boolean; icon?: React.ReactNode }) {
  return (
    <M.Item className={cn("relative flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-accent", className)} {...p}>
      {icon && <span className="text-muted-foreground [&_svg]:size-4">{icon}</span>}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {checked && <Check className="size-3.5 text-primary" />}
    </M.Item>
  );
}
