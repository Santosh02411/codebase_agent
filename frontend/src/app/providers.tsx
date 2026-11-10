"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useTheme } from "@/lib/theme";
import { useUi } from "@/lib/ui";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: false, retry: 1 } } }));
  const theme = useTheme((s) => s.theme);
  const sync = useTheme((s) => s.sync);
  // Persisted UI state is restored after hydration so the first client render matches the server HTML.
  useEffect(() => { void useUi.persist.rehydrate(); void useTheme.persist.rehydrate(); }, []);
  useEffect(() => {
    sync();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");   // follow the OS when the preference is "system"
    const on = () => useTheme.getState().pref === "system" && useTheme.getState().sync();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [sync]);
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        {children}
        <Toaster theme={theme} position="bottom-right" toastOptions={{ className: "text-xs", classNames: { toast: "!bg-panel !text-foreground !border-border !shadow-pop" } }} />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
