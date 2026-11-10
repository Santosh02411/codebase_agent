"use client";
import * as React from "react";
import * as S from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface Option { value: string; label: string; hint?: string }

export function Select({ value, onValueChange, options, placeholder, className, "aria-label": aria, disabled }: { value: string; onValueChange: (v: string) => void; options: Option[]; placeholder?: string; className?: string; "aria-label"?: string; disabled?: boolean }) {
  return (
    <S.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <S.Trigger aria-label={aria} className={cn("inline-flex h-8 items-center justify-between gap-2 rounded-md border border-input bg-panel px-2.5 text-[13px] hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:opacity-50 data-[placeholder]:text-muted-foreground", className)}>
        <span className="truncate"><S.Value placeholder={placeholder} /></span>
        <S.Icon><ChevronDown className="size-3.5 text-muted-foreground" /></S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content position="popper" sideOffset={6} className="z-50 max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg bg-panel p-1 shadow-pop data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95">
          <S.Viewport>
            {options.map((o) => (
              <S.Item key={o.value} value={o.value} className="relative flex cursor-pointer select-none items-center gap-2 rounded-md py-1.5 pl-2 pr-7 text-[13px] outline-none data-[highlighted]:bg-accent">
                <S.ItemText>{o.label}</S.ItemText>
                {o.hint && <span className="ml-auto text-[11px] text-muted-foreground">{o.hint}</span>}
                <S.ItemIndicator className="absolute right-2"><Check className="size-3.5 text-primary" /></S.ItemIndicator>
              </S.Item>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  );
}
