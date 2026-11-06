"use client";
import { useMemo, useState } from "react";
import { AlertTriangle, FlaskConical } from "lucide-react";
import { useExperiment } from "@/hooks/queries";
import type { ExpConfigResult, ExperimentResult } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

const COLS = (ks: number[]) => {
  const k5 = ks.includes(5) ? 5 : ks[Math.min(2, ks.length - 1)];
  const kmax = ks[ks.length - 1];
  return [
    { key: "mrr", label: "MRR", tip: "Mean reciprocal rank of the first relevant chunk" },
    { key: `ndcg@${kmax}`, label: `NDCG@${kmax}`, tip: "Ranking quality; each expected item counts once" },
    { key: "recall@1", label: "R@1", tip: "Share of expected items found in the top 1" },
    { key: `recall@${k5}`, label: `R@${k5}`, tip: `Share of expected items found in the top ${k5}` },
    { key: `recall@${kmax}`, label: `R@${kmax}`, tip: `Share of expected items found in the top ${kmax}` },
    { key: `precision@${k5}`, label: `P@${k5}`, tip: `Share of the top ${k5} chunks that are relevant` },
    { key: "context_precision", label: "CtxPrec", tip: "Are relevant chunks placed first in the LLM context? (RAGAS definition)" },
    { key: "context_recall", label: "CtxRecall", tip: "Share of expected items present in the token-budgeted LLM context" },
  ].filter((c, i, a) => a.findIndex((x) => x.key === c.key) === i);
};

function Heat({ v, best }: { v: number; best: boolean }) {
  return <span className={cn("rounded px-1.5 py-0.5 tabular-nums", best && "font-bold text-foreground")} style={{ background: `hsl(213 90% 55% / ${0.06 + v * 0.45})` }}>{v.toFixed(3)}</span>;
}

/** MRR with 95% bootstrap confidence intervals: overlapping whiskers = no clear winner. */
function MrrChart({ rows, level }: { rows: ExpConfigResult[]; level: "symbol" | "file" }) {
  const W = 560, rowH = 24, left = 190;
  return (
    <svg width={W} height={rows.length * rowH + 22} className="max-w-full">
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <g key={t}><line x1={left + t * (W - left - 20)} x2={left + t * (W - left - 20)} y1={0} y2={rows.length * rowH} stroke="#334155" strokeWidth={0.6} />
          <text x={left + t * (W - left - 20)} y={rows.length * rowH + 14} fontSize={10} textAnchor="middle" fill="#94a3b8">{t}</text></g>
      ))}
      {rows.map((r, i) => {
        const m = r.summary![level].mrr, x = (v: number) => left + v * (W - left - 20), y = i * rowH + rowH / 2;
        return (
          <g key={r.config.name}>
            <text x={left - 8} y={y + 4} fontSize={11} textAnchor="end" fill="#e2e8f0">{r.config.name.length > 30 ? `${r.config.name.slice(0, 29)}…` : r.config.name}</text>
            <rect x={left} y={y - 7} width={Math.max(1, x(m.mean) - left)} height={14} rx={3} fill="#3b82f6" opacity={0.85} />
            <line x1={x(m.lo)} x2={x(m.hi)} y1={y} y2={y} stroke="#f8fafc" strokeWidth={1.5} /><line x1={x(m.lo)} x2={x(m.lo)} y1={y - 5} y2={y + 5} stroke="#f8fafc" /><line x1={x(m.hi)} x2={x(m.hi)} y1={y - 5} y2={y + 5} stroke="#f8fafc" />
            <title>{`${m.mean.toFixed(3)}  (95% CI ${m.lo.toFixed(3)} – ${m.hi.toFixed(3)})`}</title>
          </g>
        );
      })}
    </svg>
  );
}

function Drilldown({ result, ok }: { result: ExperimentResult; ok: ExpConfigResult[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const hardest = useMemo(() => {
    const ids = ok[0]?.per_question?.map((q) => q.id) ?? [];
    return ids.map((id) => {
      const per = ok.map((c) => ({ cfg: c, q: c.per_question!.find((x) => x.id === id)! }));
      const ranks = per.map((p) => p.q.first_relevant_rank ?? 99);
      return { id, q: per[0].q, per, score: ranks.reduce((a, b) => a + b, 0) / ranks.length, missed: ranks.filter((r) => r === 99).length };
    }).sort((a, b) => b.score - a.score).slice(0, 12);
  }, [ok]);
  return (
    <div className="space-y-1">
      {hardest.map((h) => (
        <div key={h.id} className="rounded-md border">
          <button className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-accent/40" onClick={() => setOpen(open === h.id ? null : h.id)}>
            <Badge variant={h.missed === ok.length ? "destructive" : h.missed ? "warning" : "secondary"}>{h.missed}/{ok.length} missed</Badge>
            <span className="truncate">{h.q.question}</span><span className="ml-auto shrink-0 text-muted-foreground">{h.id}</span>
          </button>
          {open === h.id && (
            <div className="space-y-2 border-t bg-background p-3">
              <div><div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Expected</div>{h.q.expected.map((e) => <div key={e} className="font-mono text-[11px] text-success">{e}</div>)}</div>
              <div className="flex flex-wrap gap-1">{h.per.map((p) => <Badge key={p.cfg.config.name} variant={p.q.first_relevant_rank === 1 ? "success" : p.q.first_relevant_rank ? "secondary" : "destructive"}>{p.cfg.config.name}: {p.q.first_relevant_rank ? `#${p.q.first_relevant_rank}` : "missed"}</Badge>)}</div>
              <div><div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Top results of “{ok[0].config.name}”</div>
                {h.per[0].q.retrieved.slice(0, 6).map((r, i) => <div key={r} className={cn("font-mono text-[11px]", h.q.expected.includes(r) ? "text-success" : "text-muted-foreground")}>{i + 1}. {r}</div>)}</div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function ExperimentTab({ experimentId }: { experimentId: string }) {
  const q = useExperiment(experimentId);
  const [level, setLevel] = useState<"symbol" | "file">("symbol");
  const [sortKey, setSortKey] = useState("mrr");
  const r = q.data;
  const ok = useMemo(() => (r?.configs ?? []).filter((c) => c.status === "ok"), [r]);
  const cols = useMemo(() => (r ? COLS(r.ks) : []), [r]);
  const sorted = useMemo(() => [...ok].sort((a, b) => b.summary![level][sortKey].mean - a.summary![level][sortKey].mean), [ok, level, sortKey]);
  if (q.isLoading) return <div className="p-4 text-muted-foreground">Loading…</div>;
  if (q.error || !r) return <div className="p-4 text-destructive">{(q.error as Error)?.message ?? "not found"}</div>;
  const best = Object.fromEntries(cols.map((c) => [c.key, Math.max(...ok.map((x) => x.summary![level][c.key].mean))]));
  const notOk = r.configs.filter((c) => c.status !== "ok");
  return (
    <ScrollArea className="h-full">
      <div className="space-y-5 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <FlaskConical className="size-5 text-primary" />
          <div><div className="text-base font-semibold">{r.dataset.name} · {r.dataset.questions} questions</div>
            <div className="text-[11px] text-muted-foreground">{r.repo} · {r.store} · {new Date(r.created).toLocaleString()} · {r.elapsed_s}s · baseline <b className="text-foreground">{r.baseline}</b></div></div>
          <div className="ml-auto flex gap-1">
            {(["symbol", "file"] as const).map((l) => <Button key={l} size="xs" variant={level === l ? "secondary" : "ghost"} onClick={() => setLevel(l)}>{l}-level labels</Button>)}
          </div>
        </div>
        {r.label_problems.length > 0 && (
          <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3"><AlertTriangle className="size-4 shrink-0 text-warning" />
            <div><b>{r.label_problems.length} label problem(s)</b> — the dataset no longer matches this repository, so scores are unreliable:
              <ul className="mt-1 list-disc pl-4 text-[11px]">{r.label_problems.slice(0, 5).map((p) => <li key={p}>{p}</li>)}</ul></div></div>
        )}
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="bg-muted/40"><tr><th className="px-3 py-2">Configuration</th>
              {cols.map((c) => <th key={c.key} title={c.tip} onClick={() => setSortKey(c.key)} className={cn("cursor-pointer px-2 py-2 text-right hover:text-foreground", sortKey === c.key && "text-primary")}>{c.label}{sortKey === c.key ? " ↓" : ""}</th>)}
              <th className="px-2 py-2 text-right" title="Median latency per query">p50 ms</th></tr></thead>
            <tbody>
              {sorted.map((c) => {
                const cmp = r.comparisons[c.config.name]?.mrr;
                const sig = cmp && cmp.p < 0.05 ? (cmp.delta > 0 ? "▲" : "▼") : "";
                return (
                  <tr key={c.config.name} className="border-t hover:bg-accent/30">
                    <td className="px-3 py-1.5"><div className="font-medium">{c.config.name} <span className={sig === "▲" ? "text-success" : "text-destructive"} title={cmp ? `vs baseline: Δ${cmp.delta.toFixed(3)}, p=${cmp.p.toFixed(3)}` : ""}>{sig}</span></div>
                      <div className="font-mono text-[10px] text-muted-foreground">{c.config.embedder} · {c.config.mode}{c.config.reranker !== "none" ? ` · ${c.config.reranker}` : ""}{c.config.vector_weight !== 1 ? ` · wᵥ=${c.config.vector_weight}` : ""}</div></td>
                    {cols.map((col) => { const s = c.summary![level][col.key]; return <td key={col.key} className="px-2 py-1.5 text-right" title={`95% CI ${s.lo.toFixed(3)} – ${s.hi.toFixed(3)}`}><Heat v={s.mean} best={Math.abs(s.mean - best[col.key]) < 1e-9} /></td>; })}
                    <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">{c.latency_ms?.p50}</td>
                  </tr>
                );
              })}
              {notOk.map((c) => (
                <tr key={c.config.name} className="border-t text-muted-foreground"><td className="px-3 py-1.5">{c.config.name}</td>
                  <td colSpan={cols.length + 1} className="px-2 py-1.5"><Badge variant={c.status === "failed" ? "destructive" : "secondary"}>{c.status}</Badge> <span className="text-[11px]">{c.reason}</span></td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="text-[11px] text-muted-foreground">▲/▼: MRR differs from the baseline with p&lt;0.05 (paired bootstrap over questions). Hover a cell for its 95% confidence interval. With few questions most differences are <i>not</i> significant: treat unmarked gaps as noise.</div>

        {ok.length > 0 && <div><div className="mb-2 font-semibold">MRR with 95% confidence intervals</div><MrrChart rows={sorted} level={level} /></div>}

        <div>
          <div className="mb-2 font-semibold">Embedding models</div>
          <table className="w-full max-w-2xl text-left text-xs"><thead className="text-muted-foreground"><tr><th className="py-1">Model</th><th>Dim</th><th>Chunks</th><th>Index time</th><th>API calls</th><th>Tokens</th></tr></thead>
            <tbody>{Object.values(r.indexes).map((i) => <tr key={i.embedder} className="border-t"><td className="py-1 font-mono">{i.embedder}</td><td>{i.dim}</td><td>{i.chunks}</td><td>{i.seconds}s</td><td>{i.embed_calls}</td><td>{i.embed_tokens || "–"}</td></tr>)}</tbody></table>
          {Object.entries(r.skipped_embedders).map(([k, why]) => <div key={k} className="mt-1 text-[11px] text-warning">⚠ skipped <code>{k}</code>: {why}</div>)}
        </div>

        {ok.length > 0 && <div><div className="mb-2 font-semibold">Hardest questions <span className="font-normal text-muted-foreground">(highest average rank of the first relevant result across configurations)</span></div><Drilldown result={r} ok={ok} /></div>}
      </div>
    </ScrollArea>
  );
}
