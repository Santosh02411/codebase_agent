"use client";
import { useState } from "react";
import { Check, Copy, FileCode2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { useOpenFile } from "@/hooks/useOpen";
import { cn } from "@/lib/utils";
import type { Severity } from "@/lib/types";

export const SEV_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
export const SEV_VARIANT: Record<string, "destructive" | "warning" | "info" | "secondary"> = { critical: "destructive", high: "destructive", medium: "warning", low: "info", info: "secondary" };
export const SEV_COLOR: Record<string, string> = { critical: "hsl(var(--destructive))", high: "hsl(var(--destructive) / 0.8)", medium: "hsl(var(--warning))", low: "hsl(var(--info))", info: "hsl(var(--muted-foreground))" };

export function SeverityBadge({ s }: { s: Severity | string }) {
  return <Badge variant={SEV_VARIANT[s] ?? "secondary"} className="capitalize">{s}</Badge>;
}

/** A file (and optional line) that opens in the Code Explorer. */
export function FileLink({ path, line, end, className, children }: { path: string; line?: number; end?: number; className?: string; children?: React.ReactNode }) {
  const open = useOpenFile();
  return (
    <button type="button" onClick={() => open(path, line, end)} title={`Open ${path}${line ? `:${line}` : ""} in the Code Explorer`}
      className={cn("inline-flex max-w-full items-center gap-1 rounded px-1 py-0.5 font-mono text-[12px] text-primary hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60", className)}>
      <FileCode2 className="size-3 shrink-0 opacity-70" /><span className="truncate">{children ?? `${path}${line ? `:${line}` : ""}`}</span>
    </button>
  );
}

export function CopyButton({ text, className, label = "Copy" }: { text: string; className?: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" aria-label={label} onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); window.setTimeout(() => setDone(false), 1400); } catch { toast.error("Couldn’t copy to the clipboard"); } }}
      className={cn("inline-flex items-center gap-1 rounded px-1.5 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60", className)}>
      {done ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}{done ? "Copied" : label}
    </button>
  );
}

/** Circular score gauge (0-100). `value` null renders "n/a": an unmeasured score is never drawn as zero. */
export function ScoreRing({ value, size = 96, label, grade }: { value: number | null | undefined; size?: number; label?: string; grade?: string }) {
  const r = (size - 10) / 2, c = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const tone = value == null ? "hsl(var(--muted-foreground))" : v >= 80 ? "hsl(var(--success))" : v >= 60 ? "hsl(var(--warning))" : "hsl(var(--destructive))";
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }} role="img" aria-label={value == null ? "Score not available" : `${label ?? "Score"} ${Math.round(v)} out of 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth="7" style={{ stroke: "hsl(var(--secondary))" }} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth="7" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} style={{ stroke: tone, transition: "stroke-dashoffset .8s ease" }} />
      </svg>
      <div className="absolute text-center"><div className="text-xl font-semibold tabular-nums leading-none">{value == null ? "n/a" : Math.round(v)}</div>{grade && <div className="mt-0.5 text-[11px] text-muted-foreground">Grade {grade}</div>}</div>
    </div>
  );
}

export function StatusDot({ tone }: { tone: "success" | "warning" | "destructive" | "info" | "muted" | "running" }) {
  const c = { success: "bg-success", warning: "bg-warning", destructive: "bg-destructive", info: "bg-info", muted: "bg-muted-foreground/60", running: "bg-info animate-pulse-dot" }[tone];
  return <span className={cn("inline-block size-2 shrink-0 rounded-full", c)} />;
}

export const nf = (n: number | undefined | null) => (n == null ? "–" : n.toLocaleString());
export const pct = (n: number | undefined | null, d = 0) => (n == null ? "–" : `${n.toFixed(d)}%`);

/** Chart tooltip that follows the theme (recharts renders its own, unthemed one otherwise). */
export function ChartTip({ active, payload, label, unit }: { active?: boolean; payload?: { name?: string; value?: number | string; color?: string; payload?: Record<string, unknown> }[]; label?: string; unit?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg bg-panel px-2.5 py-1.5 text-xs shadow-pop">
      {label && <div className="mb-1 font-medium">{label}</div>}
      {payload.map((p, i) => <div key={i} className="flex items-center gap-1.5"><span className="size-2 rounded-sm" style={{ background: p.color }} /><span className="text-muted-foreground">{p.name}</span><span className="ml-auto pl-3 font-medium tabular-nums">{typeof p.value === "number" ? p.value.toLocaleString() : p.value}{unit}</span></div>)}
    </div>
  );
}
export const CHART = ["hsl(var(--chart-1))", "hsl(var(--chart-2))", "hsl(var(--chart-3))", "hsl(var(--chart-4))", "hsl(var(--chart-5))", "hsl(var(--chart-6))"];

/** Shown whenever an AI-looking result came from the offline mock model, which cannot reason about code. */
export function MockNotice({ llm, className }: { llm?: string; className?: string }) {
  if (!llm || !llm.toLowerCase().startsWith("mock")) return null;
  return <div role="note" className={cn("flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/8 px-3 py-2 text-xs", className)}><span className="mt-0.5 size-2 shrink-0 rounded-full bg-warning" /><span><span className="font-medium text-warning">Offline mock model.</span> <span className="text-muted-foreground">This was assembled from code retrieval only. No AI reasoning happened, so treat it as a list of relevant code, not an analysis. Configure a model to get real answers (docs/ENV_SETUP.md).</span></span></div>;
}

/** Plain-language help for the model errors people actually hit. Matches on the provider's own error text. */
export function modelErrorHint(text?: string): string | null {
  const t = (text ?? "").toLowerCase();
  if (!t) return null;
  if (t.includes("resource_exhausted") || t.includes("quota") || t.includes("429")) return "The model provider says this API key has no quota left (a per-minute or per-day limit, common on free tiers). The app already tried other models. Wait for the limit to reset, enable billing for the key, or switch the provider/key in .env (docs/ENV_SETUP.md).";
  if (t.includes("api_key_invalid") || t.includes("api key not valid") || t.includes("401") || t.includes("403") || t.includes("permission_denied") || t.includes("authentication")) return "The provider rejected the API key. Check GEMINI_API_KEY / OPENAI_API_KEY in .env (no quotes, no spaces), make sure the key is active, and restart the backend.";
  if (t.includes("is not set")) return "No API key is configured for this provider. Add it to .env and restart the backend, or switch LLM_PROVIDER to mock to work without AI.";
  if (t.includes("no longer available") || t.includes("404") || t.includes("not found")) return "The configured model name does not exist for this key. Leave LLM_MODEL empty in .env and the app will pick a current model, or set a model name your key can use.";
  if (t.includes("503") || t.includes("unavailable") || t.includes("high demand") || t.includes("504") || t.includes("deadline")) return "The model is overloaded or timed out. This is temporary on the provider's side; try again in a minute.";
  return null;
}
