"use client";
import { usePathname } from "next/navigation";
import { GitBranch, Menu, Search } from "lucide-react";
import { NAV } from "@/lib/nav";
import { useUi } from "@/lib/ui";
import { useCurrentRepo } from "@/hooks/useCurrentRepo";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Kbd } from "@/components/ui/misc";
import { IndexStatus } from "./IndexStatus";
import { Notifications } from "./Notifications";
import { ProfileMenu } from "./ProfileMenu";
import { ThemeMenu } from "./ThemeMenu";

export function Topbar() {
  const path = usePathname();
  const { repo } = useCurrentRepo();
  const setPalette = useUi((s) => s.setPalette);
  const setMobile = useUi((s) => s.setMobileNav);
  const page = NAV.find((n) => (n.href === "/" ? path === "/" : path.startsWith(n.href)));
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobile(true)} aria-label="Open navigation"><Menu /></Button>
      <div className="flex min-w-0 items-center gap-2 text-[13px]">
        <span className="hidden truncate text-muted-foreground sm:inline">{repo?.name ?? "No project"}</span>
        {repo?.branch && <Badge variant="secondary" className="hidden gap-1 sm:inline-flex"><GitBranch className="size-3" />{repo.branch}</Badge>}
        <span className="hidden text-muted-foreground/50 sm:inline">/</span>
        <h2 className="truncate font-medium">{page?.label ?? "CodeScout AI"}</h2>
      </div>
      <div className="mx-auto hidden w-full max-w-md md:block">
        <button onClick={() => setPalette(true)} className="flex h-8 w-full items-center gap-2 rounded-md border border-input bg-panel px-2.5 text-left text-[13px] text-muted-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60" aria-label="Search files, symbols and commands">
          <Search className="size-3.5" /><span className="flex-1 truncate">Search files, symbols, commands…</span><Kbd>Ctrl K</Kbd>
        </button>
      </div>
      <div className="ml-auto flex items-center gap-1.5 md:ml-0">
        <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setPalette(true)} aria-label="Search"><Search /></Button>
        <div className="hidden sm:block"><IndexStatus /></div>
        <Notifications />
        <ThemeMenu />
        <ProfileMenu />
      </div>
    </header>
  );
}
