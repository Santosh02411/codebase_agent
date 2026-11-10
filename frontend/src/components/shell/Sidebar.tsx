"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { GROUPS, NAV } from "@/lib/nav";
import { useUi } from "@/lib/ui";
import { useHealth } from "@/hooks/queries";
import { cn } from "@/lib/utils";
import { Tip } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Logo } from "./Logo";
import { ProjectSwitcher } from "./ProjectSwitcher";

const isActive = (path: string, href: string) => (href === "/" ? path === "/" : path === href || path.startsWith(href + "/"));

export function SidebarContent({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const path = usePathname();
  const health = useHealth();
  const setCollapsed = useUi((s) => s.setCollapsed);
  const groups = (Object.keys(GROUPS) as (keyof typeof GROUPS)[]).map((g) => ({ g, items: NAV.filter((n) => n.group === g) }));
  return (
    <div className="flex h-full flex-col">
      <div className={cn("flex h-14 shrink-0 items-center gap-2.5 px-4", collapsed && "justify-center px-0")}>
        <Logo />
        {!collapsed && <div className="min-w-0 leading-tight"><div className="truncate text-[13px] font-semibold">CodeScout AI</div><div className="truncate text-[11px] text-muted-foreground">AI-powered code review</div></div>}
      </div>
      <div className={cn("shrink-0 px-3 pb-3", collapsed && "px-2")}><ProjectSwitcher collapsed={collapsed} /></div>
      <nav aria-label="Main" className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 pb-3">
        {groups.map(({ g, items }) => (
          <div key={g}>
            {!collapsed && <div className="px-2 pb-1 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground/80">{GROUPS[g]}</div>}
            <ul className="space-y-0.5">
              {items.map((n) => {
                const active = isActive(path, n.href);
                const link = (
                  <Link href={n.href} onClick={onNavigate} aria-current={active ? "page" : undefined}
                    className={cn("group relative flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] font-medium transition-colors", collapsed && "justify-center px-0 py-2",
                      active ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground")}>
                    {active && <span className="absolute -left-3 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r bg-primary" />}
                    <n.icon className={cn("size-4 shrink-0", active && "text-primary")} />
                    {!collapsed && <span className="truncate">{n.label}</span>}
                    {collapsed && <span className="sr-only">{n.label}</span>}
                  </Link>
                );
                return <li key={n.href}>{collapsed ? <Tip side="right" label={n.label}>{link}</Tip> : link}</li>;
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className={cn("flex shrink-0 items-center gap-2 border-t px-3 py-2.5", collapsed && "flex-col px-2")}>
        <Tip side="right" label={health.isError ? "Backend unreachable" : `Backend connected · LLM: ${health.data?.llm_provider ?? "…"}`}>
          <span className={cn("flex min-w-0 items-center gap-2 text-[11px] text-muted-foreground", collapsed && "justify-center")}>
            <span className={cn("size-2 shrink-0 rounded-full", health.isError ? "bg-destructive" : health.data ? "bg-success" : "animate-pulse-dot bg-muted-foreground")} />
            {!collapsed && <span className="truncate">{health.isError ? "Backend offline" : health.data ? `${health.data.llm_provider}${health.data.llm_provider === "mock" ? " (offline mock)" : ""}` : "Connecting…"}</span>}
          </span>
        </Tip>
        <Button variant="ghost" size="icon-sm" className={cn("hidden lg:inline-flex", !collapsed && "ml-auto")} onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </Button>
      </div>
    </div>
  );
}
