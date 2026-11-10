"use client";
import { DebugPage } from "@/components/debug/DebugPage";
import { RequireProject } from "@/components/shell/RequireProject";

export default function Page() {
  return <RequireProject>{(id) => <DebugPage repoId={id} />}</RequireProject>;
}
