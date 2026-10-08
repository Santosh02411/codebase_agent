"use client";
import dynamic from "next/dynamic";

// Monaco and the persisted store only make sense in the browser.
const Workbench = dynamic(() => import("@/components/ide/Workbench").then((m) => m.Workbench), {
  ssr: false,
  loading: () => <div className="flex h-screen items-center justify-center text-muted-foreground">Loading workspace…</div>,
});

export default function Page() {
  return <Workbench />;
}
