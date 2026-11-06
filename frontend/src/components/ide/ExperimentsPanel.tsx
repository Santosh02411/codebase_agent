"use client";
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Loader2, Play } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useDatasets, useExperimentJob, useExperiments, useRagInfo } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

const PRESETS = {
  offline: { label: "Offline baseline (no API keys)", embedders: "hash", rerankers: "heuristic" },
  compare: { label: "Compare embedding models", embedders: "hash,openai:text-embedding-3-small,gemini:gemini-embedding-001,bge:BAAI/bge-small-en-v1.5", rerankers: "heuristic,bge-reranker-base" },
} as const;

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex gap-2 py-0.5"><span className="w-24 shrink-0 text-muted-foreground">{k}</span><span className="min-w-0 break-words">{v}</span></div>;
}

export function ExperimentsPanel({ repoId }: { repoId: string }) {
  const rag = useRagInfo();
  const datasets = useDatasets();
  const runs = useExperiments();
  const qc = useQueryClient();
  const openExperiment = useIde((s) => s.openExperiment);
  const [dataset, setDataset] = useState("");
  const [preset, setPreset] = useState<keyof typeof PRESETS>("offline");
  const [embedders, setEmbedders] = useState<string>(PRESETS.offline.embedders);
  const [rerankers, setRerankers] = useState<string>(PRESETS.offline.rerankers);
  const [pg, setPg] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useExperimentJob(jobId);

  useEffect(() => { if (!dataset && datasets.data?.length) setDataset(datasets.data[0].name); }, [datasets.data, dataset]);
  useEffect(() => { setEmbedders(PRESETS[preset].embedders); setRerankers(PRESETS[preset].rerankers); }, [preset]);
  useEffect(() => {
    const j = job.data;
    if (!j || j.state === "running") return;
    setJobId(null);
    qc.invalidateQueries({ queryKey: ["experiments"] });
    if (j.state === "done" && j.result_id) { toast.success("Experiment finished"); openExperiment(j.result_id, "Experiment"); }
    else toast.error(j.error || "Experiment failed");
  }, [job.data, qc, openExperiment]);

  const start = useMutation({
    mutationFn: () => api.runExperiment({ repo_id: repoId, dataset, embedders: embedders.split(",").map((s) => s.trim()).filter(Boolean), rerankers: rerankers.split(",").map((s) => s.trim()).filter(Boolean), use_pgvector: pg }),
    onSuccess: (r) => setJobId(r.job_id),
    onError: (e: Error) => toast.error(e.message),
  });
  const running = !!jobId || start.isPending;
  const ds = datasets.data?.find((d) => d.name === dataset);
  const r = rag.data;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="px-3 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Retrieval experiments</div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-4 px-3 pb-4">
          <div className="rounded-lg border bg-background p-2.5">
            <div className="mb-1 font-medium">Current pipeline</div>
            {r ? (
              <>
                <Row k="Storage" v={<Badge variant={r.store === "pgvector" ? "success" : "secondary"}>{r.store === "pgvector" ? "PostgreSQL + pgvector" : "in-memory"}</Badge>} />
                <Row k="Embeddings" v={r.embedding.error ? <span className="text-destructive">{r.embedding.error}</span> : `${r.embedding.name} (${r.embedding.dim} dims)`} />
                <Row k="Retrieval" v={`${r.retrieval.mode} · BM25 + vectors, RRF k=${r.retrieval.rrf_k}, vector weight ${r.retrieval.vector_weight}`} />
                <Row k="Reranker" v={r.reranker} /><Row k="Context" v={`${r.context_token_budget} tokens, cited with [n]`} />
                {r.models.map((m) => <Row key={m.table} k="Vectors" v={`${m.model}: ${m.vectors.toLocaleString()} (${m.hnsw ? "HNSW" : "exact scan"})`} />)}
              </>
            ) : <div className="text-muted-foreground">Loading…</div>}
          </div>

          <div className="space-y-2">
            <div className="font-medium">Run a benchmark</div>
            <select value={dataset} onChange={(e) => setDataset(e.target.value)} className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs" disabled={running}>
              {datasets.data?.map((d) => <option key={d.name} value={d.name}>{d.name} · {d.questions} questions</option>)}
            </select>
            {ds && <div className="text-[11px] text-muted-foreground">{ds.description}{ds.repo && <> Labels expect repository <code>{ds.repo}</code> — import it first, otherwise scores will be unreliable (the result will warn you).</>}</div>}
            <select value={preset} onChange={(e) => setPreset(e.target.value as keyof typeof PRESETS)} className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs" disabled={running}>
              {Object.entries(PRESETS).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
            </select>
            <Input value={embedders} onChange={(e) => setEmbedders(e.target.value)} disabled={running} placeholder="embedding models, comma separated" className="font-mono text-[11px]" />
            <Input value={rerankers} onChange={(e) => setRerankers(e.target.value)} disabled={running} placeholder="rerankers, comma separated" className="font-mono text-[11px]" />
            {r?.store === "pgvector" && <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><input type="checkbox" checked={pg} onChange={(e) => setPg(e.target.checked)} disabled={running} /> Run against PostgreSQL (adds each model to the same chunks)</label>}
            <div className="text-[11px] text-muted-foreground">Models whose API key or package is missing are skipped. API models embed the whole repository once, which costs tokens.</div>
            <Button size="sm" className="w-full" disabled={running || !dataset} onClick={() => start.mutate()}>{running ? <><Loader2 className="animate-spin" /> {job.data ? `${job.data.phase} ${job.data.done}/${job.data.total}` : "Starting…"}</> : <><Play /> Run experiment</>}</Button>
          </div>

          <div>
            <div className="mb-1 font-medium">Saved runs</div>
            {runs.data?.length === 0 && <div className="text-muted-foreground">None yet.</div>}
            {runs.data?.map((e) => (
              <button key={e.id} onClick={() => openExperiment(e.id, `Experiment: ${e.dataset}`)} className="mb-1.5 block w-full rounded-md border bg-background p-2 text-left hover:border-primary">
                <div className="flex items-center gap-1.5"><FlaskConical className="size-3.5 text-primary" /><span className="font-medium">{e.dataset}</span><Badge variant="outline" className="ml-auto">{e.store}</Badge></div>
                <div className="text-[11px] text-muted-foreground">{new Date(e.created).toLocaleString()} · {e.configs} configs{e.skipped ? ` (${e.skipped} skipped)` : ""}</div>
                {e.best && <div className={cn("mt-0.5 text-[11px]")}>best: <b>{e.best.name}</b> · MRR {e.best.mrr.toFixed(3)}</div>}
              </button>
            ))}
          </div>
        </div>
      </ScrollArea>
    </div>
  );
}
