"use client";
import { ExplorerPage } from "@/components/explorer/ExplorerPage";
import { RequireProject } from "@/components/shell/RequireProject";

export default function Page() {
  return <RequireProject>{(id) => <ExplorerPage repoId={id} />}</RequireProject>;
}
