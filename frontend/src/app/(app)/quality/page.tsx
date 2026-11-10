"use client";
import { QualityPage } from "@/components/quality/QualityPage";
import { RequireProject } from "@/components/shell/RequireProject";

export default function Page() {
  return <RequireProject>{(id) => <QualityPage repoId={id} />}</RequireProject>;
}
