"use client";
import { ArchHub } from "@/components/arch/ArchHub";
import { RequireProject } from "@/components/shell/RequireProject";

export default function Page() {
  return <RequireProject>{(id) => <ArchHub repoId={id} />}</RequireProject>;
}
