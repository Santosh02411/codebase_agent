"use client";
import { CheckCircle2, Loader2, TriangleAlert } from "lucide-react";
import { useActiveIndexing } from "@/hooks/queries";
import { useCurrentRepo } from "@/hooks/useCurrentRepo";
import { Badge } from "@/components/ui/badge";
import { Tip } from "@/components/ui/tooltip";

export const ago = (iso?: string | number) => {
  if (!iso) return "";
  const t = typeof iso === "number" ? iso * (iso < 1e12 ? 1000 : 1) : new Date(iso).getTime();
  const s = Math.max(0, (Date.now() - t) / 1000);
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : `${Math.floor(s / 86400)} d ago`;
};

/** Live indexing state of the selected project (polls fast only while something is indexing). */
export function IndexStatus() {
  const { repo, repoId } = useCurrentRepo();
  const active = useActiveIndexing(!!repoId);
  if (!repo || !repoId) return null;
  const st = active.data?.[repoId];
  if (st?.state === "indexing") {
    const pct = st.total ? Math.round(((st.done ?? 0) / st.total) * 100) : null;
    return <Tip label={`${st.phase ?? "Indexing"}${st.total ? ` · ${st.done}/${st.total}` : ""}`}><Badge variant="info" className="gap-1.5"><Loader2 className="size-3 animate-spin" />Indexing{pct != null ? ` ${pct}%` : "…"}</Badge></Tip>;
  }
  if (st?.state === "error") return <Tip label={st.error ?? "Indexing failed"}><Badge variant="destructive" className="gap-1.5"><TriangleAlert className="size-3" />Index error</Badge></Tip>;
  return <Tip label={`${repo.files} files · ${repo.chunks} chunks · ${repo.embedder} embeddings · indexed ${ago(repo.indexed_at)}`}><Badge variant="success" className="gap-1.5"><CheckCircle2 className="size-3" />Indexed</Badge></Tip>;
}
