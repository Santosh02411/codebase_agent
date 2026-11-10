"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUp, FileCode2, FunctionSquare, ImagePlus, Square, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useStats, useTree } from "@/hooks/queries";
import { useIde } from "@/store/ide";
import { basename, cn, fuzzy } from "@/lib/utils";
import type { Mode } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Segmented, Switch } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/input";
import { MODES, suggestionsFor } from "./modes";

interface Mention { kind: "file" | "symbol"; label: string; insert: string; hint?: string }

function fileToShot(f: File): Promise<{ media_type: string; data: string; name: string }> {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res({ media_type: f.type || "image/png", data: String(r.result).split(",")[1] ?? "", name: f.name }); r.onerror = () => rej(r.error); r.readAsDataURL(f); });
}

export function Composer({ repoId, running, onSend, onStop, showSuggestions }: { repoId: string; running: boolean; onSend: (mode: Mode, text: string, target?: string) => void; onStop: () => void; showSuggestions: boolean }) {
  const mode = useIde((s) => s.mode), setMode = useIde((s) => s.setMode);
  const provider = useIde((s) => s.provider), setProvider = useIde((s) => s.setProvider);
  const verify = useIde((s) => s.verify), setVerify = useIde((s) => s.setVerify);
  const attachment = useIde((s) => s.attachment), setAttachment = useIde((s) => s.setAttachment);
  const shots = useIde((s) => s.screenshots), addShot = useIde((s) => s.addScreenshot), removeShot = useIde((s) => s.removeScreenshot);
  const [text, setText] = useState("");
  const [sel, setSel] = useState(0);
  const ref = useRef<HTMLTextAreaElement>(null);
  const stats = useStats(repoId);
  const tree = useTree(repoId);
  const def = MODES.find((m) => m.mode === mode) ?? MODES[0];

  // @mention: the token being typed at the end of the text
  const token = /(^|\s)@([\w./\-]*)$/.exec(text)?.[2];
  const symbols = useQuery({ queryKey: ["mention-symbols", repoId, token], queryFn: () => api.symbols(repoId, { q: token }), enabled: token !== undefined && token.length >= 2, staleTime: 15_000 });
  const mentions = useMemo<Mention[]>(() => {
    if (token === undefined) return [];
    const files = (tree.data ?? []).map((f) => ({ f, s: token ? Math.max(fuzzy(token, basename(f)) + 2, fuzzy(token, f)) : 0 })).filter((x) => x.s >= 0).sort((a, b) => b.s - a.s).slice(0, 5)
      .map<Mention>(({ f }) => ({ kind: "file", label: basename(f), insert: f, hint: f }));
    const syms = (symbols.data ?? []).slice(0, 4).map<Mention>((s) => ({ kind: "symbol", label: s.qualname, insert: s.qualname, hint: `${s.file}:${s.start}` }));
    return [...files, ...syms];
  }, [token, tree.data, symbols.data]);
  useEffect(() => { setSel(0); }, [token]);

  useEffect(() => {
    const f = () => ref.current?.focus();
    window.addEventListener("agent:focus-chat", f);
    return () => window.removeEventListener("agent:focus-chat", f);
  }, []);
  useEffect(() => { const t = ref.current; if (t) { t.style.height = "auto"; t.style.height = `${Math.min(t.scrollHeight, 220)}px`; } }, [text]);

  const pick = (m: Mention) => { setText((t) => t.replace(/@([\w./\-]*)$/, m.kind === "file" ? `${m.insert} ` : `\`${m.insert}\` `)); ref.current?.focus(); };
  const submit = () => {
    const t = text.trim();
    if (running || (!t && !shots.length && !attachment)) return;
    const target = (mode === "tests" || mode === "review") ? (attachment?.file ?? (t.match(/(?:^|\s)([\w.\-]+(?:\/[\w.\-]+)+|[\w\-]+\.(?:py|js|ts|tsx|jsx|java|go|rs))(?=\s|$)/)?.[1])) : undefined;
    onSend(mode, t, target && (tree.data ?? []).includes(target) ? target : undefined);
    setText("");
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (mentions.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); setSel((i) => Math.min(i + 1, mentions.length - 1)); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setSel((i) => Math.max(i - 1, 0)); return; }
      if (e.key === "Tab" || e.key === "Enter") { e.preventDefault(); pick(mentions[sel]); return; }
      if (e.key === "Escape") { e.preventDefault(); setText((t) => t.replace(/@([\w./\-]*)$/, "")); return; }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
  };
  const onPaste = async (e: React.ClipboardEvent) => {
    const imgs = [...e.clipboardData.files].filter((f) => f.type.startsWith("image/"));
    if (!imgs.length) return;
    e.preventDefault();
    for (const f of imgs.slice(0, 3)) { try { addShot(await fileToShot(f)); } catch { toast.error("Couldn’t read that image"); } }
  };
  const insights = useQuery({ queryKey: ["insights", repoId], queryFn: () => api.insights(repoId), staleTime: 60_000 });
  const sug = suggestionsFor(mode, stats.data, insights.data);
  const suggestions = sug.items;

  return (
    <div className="space-y-2.5">
      {showSuggestions && (
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Prompt suggestions">
          <span className="text-[11px] text-muted-foreground">{sug.derived ? "From your code:" : "Generic ideas (no project-specific facts available):"}</span>
          {suggestions.map((s) => <button key={s} onClick={() => { setText(s); ref.current?.focus(); }} className="rounded-full border bg-panel px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-foreground">{s}</button>)}
        </div>
      )}
      <div className="relative rounded-xl bg-panel shadow-card focus-within:ring-2 focus-within:ring-ring/40">
        {mentions.length > 0 && (
          <ul role="listbox" aria-label="Mentions" className="absolute bottom-full left-2 z-20 mb-2 w-[min(28rem,calc(100%-1rem))] overflow-hidden rounded-lg bg-panel p-1 shadow-pop">
            {mentions.map((m, i) => (
              <li key={`${m.kind}:${m.insert}`}><button role="option" aria-selected={i === sel} onMouseDown={(e) => { e.preventDefault(); pick(m); }} onMouseMove={() => setSel(i)} className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px]", i === sel && "bg-accent")}>
                {m.kind === "file" ? <FileCode2 className="size-3.5 text-muted-foreground" /> : <FunctionSquare className="size-3.5 text-muted-foreground" />}<span className="truncate">{m.label}</span><span className="ml-auto max-w-[55%] truncate text-xs text-muted-foreground">{m.hint}</span>
              </button></li>
            ))}
          </ul>
        )}
        {(attachment || shots.length > 0) && (
          <div className="flex flex-wrap gap-2 border-b px-3 py-2">
            {attachment && <span className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-secondary px-2 py-1 font-mono text-[11px]"><FileCode2 className="size-3" /><span className="truncate">{attachment.file}:{attachment.startLine}-{attachment.endLine}</span><button aria-label="Remove selected code" onClick={() => setAttachment(null)}><X className="size-3" /></button></span>}
            {shots.map((s, i) => <span key={i} className="inline-flex items-center gap-1.5 rounded-md bg-secondary px-2 py-1 text-[11px]"><ImagePlus className="size-3" />{s.name ?? `screenshot ${i + 1}`}<button aria-label="Remove screenshot" onClick={() => removeShot(i)}><X className="size-3" /></button></span>)}
          </div>
        )}
        <Textarea ref={ref} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKeyDown} onPaste={onPaste} rows={2} placeholder={def.placeholder} aria-label="Message to the agent"
          className="min-h-[52px] border-0 bg-transparent px-3.5 pt-3 text-[13.5px] shadow-none focus-visible:ring-0" />
        <div className="flex flex-wrap items-center gap-2 px-2.5 pb-2.5">
          <Segmented size="sm" value={mode} onChange={setMode} options={MODES.map((m) => ({ value: m.mode, label: m.label, icon: <m.icon />, title: m.blurb }))} />
          <div className="ml-auto flex items-center gap-2">
            {def.needsVerify && <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><Switch checked={verify} onCheckedChange={setVerify} label="Verify with tests" />Verify</label>}
            <Select aria-label="Model provider" className="h-7 w-[104px] text-xs" value={provider || "default"} onValueChange={(v) => setProvider(v === "default" ? "" : v)}
              options={[{ value: "default", label: "Default model" }, { value: "gemini", label: "Gemini" }, { value: "openai", label: "OpenAI" }, { value: "mock", label: "Offline mock" }]} />
            {running
              ? <Button size="icon-sm" variant="destructive" onClick={onStop} aria-label="Stop the agent"><Square className="fill-current" /></Button>
              : <Button size="icon-sm" onClick={submit} disabled={!text.trim() && !shots.length && !attachment} aria-label="Send"><ArrowUp /></Button>}
          </div>
        </div>
      </div>
      <p className="px-1 text-[11px] text-muted-foreground">{def.blurb} <span className="hidden sm:inline">Enter to send · Shift+Enter for a new line · paste a screenshot to include it.</span></p>
    </div>
  );
}
