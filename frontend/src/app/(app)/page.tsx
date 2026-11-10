"use client";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { RequireProject } from "@/components/shell/RequireProject";

export default function Page() {
  return <RequireProject>{(id) => <Dashboard repoId={id} />}</RequireProject>;
}
