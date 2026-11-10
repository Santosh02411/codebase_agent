"use client";
import dynamic from "next/dynamic";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

// Monaco and the persisted store only make sense in the browser.
const Workbench = dynamic(() => import("@/components/ide/Workbench").then((m) => m.Workbench), {
  ssr: false,
  loading: () => <div className="flex h-screen items-center justify-center text-muted-foreground">Loading workspace…</div>,
});

export default function Page() {
  return (
    <>
      <Workbench />
      <Link href="/" className="fixed bottom-8 right-4 z-[70] inline-flex items-center gap-1.5 rounded-full bg-primary px-3.5 py-2 text-xs font-medium text-primary-foreground shadow-pop hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft className="size-3.5" />Back to CodeScout AI
      </Link>
    </>
  );
}
