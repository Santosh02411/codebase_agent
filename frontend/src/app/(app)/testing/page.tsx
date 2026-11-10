"use client";
import { TestingPage } from "@/components/testing/TestingPage";
import { RequireProject } from "@/components/shell/RequireProject";

export default function Page() {
  return <RequireProject>{(id) => <TestingPage repoId={id} />}</RequireProject>;
}
