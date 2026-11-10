"use client";
import { ChangesPage } from "@/components/patches/ChangesPage";
import { RequireProject } from "@/components/shell/RequireProject";

export default function Page() {
  return <RequireProject>{(id) => <ChangesPage repoId={id} />}</RequireProject>;
}
