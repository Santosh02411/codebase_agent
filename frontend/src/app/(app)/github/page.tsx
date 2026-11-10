"use client";
import { GitHubPage } from "@/components/github/GitHubPage";
import { RequireProject } from "@/components/shell/RequireProject";

export default function Page() {
  return <RequireProject>{(id) => <GitHubPage repoId={id} />}</RequireProject>;
}
