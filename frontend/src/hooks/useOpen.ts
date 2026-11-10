"use client";
import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { useIde } from "@/store/ide";

/** Open a file (optionally at a line range) in the Code Explorer: a deep link, so the browser back button works. */
export function useOpenFile() {
  const router = useRouter();
  return useCallback((path: string, line?: number, endLine?: number) => {
    const q = new URLSearchParams({ file: path });
    if (line) q.set("line", String(line));
    if (endLine && endLine !== line) q.set("end", String(endLine));
    router.push(`/explorer?${q.toString()}`);
  }, [router]);
}

/** Pre-fill the chat composer with a question about some code and go to the chat. */
export function useAskAbout() {
  const router = useRouter();
  return useCallback((sel?: { file: string; startLine: number; endLine: number; text: string }) => {
    if (sel) useIde.getState().setAttachment(sel);
    router.push("/chat");
  }, [router]);
}
