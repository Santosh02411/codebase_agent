"use client";
import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { useUi } from "@/lib/ui";
import { cn } from "@/lib/utils";
import { useHealth } from "@/hooks/queries";
import { AddRepoDialog } from "@/components/ide/AddRepoDialog";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { CommandMenu } from "./CommandMenu";
import { SidebarContent } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const collapsed = useUi((s) => s.collapsed);
  const mobile = useUi((s) => s.mobileNav);
  const setMobile = useUi((s) => s.setMobileNav);
  const addProject = useUi((s) => s.addProject);
  const setAdd = useUi((s) => s.setAddProject);
  const path = usePathname();
  const health = useHealth();
  useEffect(() => { setMobile(false); }, [path, setMobile]);
  // Safety net: if a dialog or menu closes while the page is blocked (`pointer-events: none` on <body>), release it. Without an open modal nothing should block clicks.
  useEffect(() => {
    const release = () => {
      if (document.body.style.pointerEvents === "none" && !document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]')) document.body.style.pointerEvents = "";
    };
    const mo = new MutationObserver(() => window.setTimeout(release, 120));
    mo.observe(document.body, { attributes: true, attributeFilter: ["style"] });
    const t = window.setInterval(release, 1500);
    return () => { mo.disconnect(); window.clearInterval(t); };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") { e.preventDefault(); const u = useUi.getState(); u.setCollapsed(!u.collapsed); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <a href="#main" className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:absolute focus:left-3 focus:top-3">Skip to content</a>
      <aside className={cn("hidden shrink-0 border-r bg-sidebar transition-[width] duration-200 lg:block", collapsed ? "w-[60px]" : "w-64")}><SidebarContent collapsed={collapsed} /></aside>
      <Dialog open={mobile} onOpenChange={setMobile}>
        <DialogContent title="Navigation" hideClose className="left-0 top-0 h-full max-h-none w-72 max-w-[85vw] translate-x-0 translate-y-0 rounded-none bg-sidebar p-0 data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-left">
          <SidebarContent collapsed={false} onNavigate={() => setMobile(false)} />
        </DialogContent>
      </Dialog>
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        {health.isError && (
          <div role="alert" className="flex items-center gap-2 border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive">
            <AlertTriangle className="size-3.5 shrink-0" /><span className="min-w-0 truncate">{(health.error as Error).message}</span>
          </div>
        )}
        <main id="main" className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
      <CommandMenu />
      {addProject && <AddRepoDialog onClose={() => setAdd(false)} />}
    </div>
  );
}
