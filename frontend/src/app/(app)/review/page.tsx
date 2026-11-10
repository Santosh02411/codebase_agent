"use client";
import { ReviewPage } from "@/components/review/ReviewPage";
import { RequireProject } from "@/components/shell/RequireProject";

export default function Page() {
  return <RequireProject>{(id) => <ReviewPage repoId={id} />}</RequireProject>;
}
