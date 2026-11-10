"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { FileCode2, FlaskConical, FunctionSquare, Moon, Plus, RefreshCw, Search, Sun } from "lucide-react";
import { api } from "@/lib/api";
import { NAV } from "@/lib/nav";
import { useUi } from "@/lib/ui";
import { useTheme } from "@/lib/theme";
import { fuzzy, cn, basename } from "@/lib/utils";
import { useReindex, useTree } from "@/hooks/queries";
import { useCurrentRepo } from "@/hooks/useCurrentRepo";
import { useOpenFile } from "@/hooks/useOpen";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/misc";

interface Cmd { id: string; group: string; label: string; hint?: string; icon: React.ReactNode; run: () => void }

export function CommandMenu() {
  const open = useUi((s) => s.palette);
  const setOpen = useUi((s) => s.setPalette);
  const setAdd = useUi((s) => s.setAddProject);
  const router = useRouter();
  const openFile = useOpenFile();
  const { repoId } = useCurrentRepo();
  const tree = useTree(repoId);
  const reindex = useReindex();
  const theme = useTheme((s) => s.theme);
  const setPref = useTheme((s) => s.setPref);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); useUi.getState().setPalette(!useUi.getState().palette); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { if (open) { setQ(""); setSel(0); } }, [open]);

  const symbols = useQuery({ queryKey: ["palette-symbols", repoId, q], queryFn: () => api.symbols(repoId!, { q }), enabled: !!repoId && open && q.trim().length >= 2, staleTime: 15_000 });

  const cmds = useMemo<Cmd[]>(() => {
    const go = (href: string) => () => router.push(href);
    const base: Cmd[] = [
      ...NAV.map((n) => ({ id: `nav:${n.href}`, group: "Go to", label: n.label, hint: n.hint, icon: <n.icon className="size-4" />, run: go(n.href) })),
      { id: "act:add", group: "Actions", label: "Add project…", icon: <Plus className="size-4" />, run: () => setAdd(true) },
      ...(repoId ? [
        { id: "act:tests", group: "Actions", label: "Run tests", icon: <FlaskConical className="size-4" />, run: () => router.push("/testing?run=1") },
        { id: "act:reindex", group: "Actions", label: "Re-index project", icon: <RefreshCw className="size-4" />, run: () => reindex.mutate(repoId) },
      ] : []),
      { id: "act:theme", group: "Actions", label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme", icon: theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />, run: () => setPref(theme === "dark" ? "light" : "dark") },
    ];
    const query = q.trim();
    if (!query) return base;
    const scored = base.map((c) => ({ c, s: fuzzy(query, c.label) })).filter((x) => x.s >= 0).sort((a, b) => b.s - a.s).map((x) => x.c);
    const files = (tree.data ?? []).map((f) => ({ f, s: Math.max(fuzzy(query, basename(f)) + 2, fuzzy(query, f)) })).filter((x) => x.s >= 0).sort((a, b) => b.s - a.s).slice(0, 8)
      .map<Cmd>(({ f }) => ({ id: `file:${f}`, group: "Files", label: basename(f), hint: f, icon: <FileCode2 className="size-4" />, run: () => openFile(f) }));
    const syms = (symbols.data ?? []).slice(0, 8).map<Cmd>((s) => ({ id: `sym:${s.id}`, group: "Symbols", label: s.qualname, hint: `${s.file}:${s.start}`, icon: <FunctionSquare className="size-4" />, run: () => openFile(s.file, s.start, s.end) }));
    return [...scored, ...files, ...syms];
  }, [q, tree.data, symbols.data, repoId, theme, router, openFile, reindex, setAdd, setPref]);

  useEffect(() => { setSel(0); }, [q]);
  useEffect(() => { listRef.current?.querySelector<HTMLElement>(`[data-i="${sel}"]`)?.scrollIntoView({ block: "nearest" }); }, [sel]);

  const run = (c?: Cmd) => { if (!c) return; setOpen(false); c.run(); };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((i) => Math.min(i + 1, cmds.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); run(cmds[sel]); }
  };
  let last = "";
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent title="Command palette" description="Search pages, files, symbols and actions" hideClose className="top-[18%] max-w-xl translate-y-0 p-0">
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="size-4 text-muted-foreground" />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKeyDown} placeholder="Type a page, file, symbol or command…" role="combobox" aria-expanded aria-controls="cmd-list" aria-activedescendant={`cmd-${sel}`}
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
          <Kbd>Esc</Kbd>
        </div>
        <ul id="cmd-list" role="listbox" ref={listRef} className="max-h-[50vh] overflow-y-auto p-1.5">
          {cmds.length === 0 && <li className="px-3 py-8 text-center text-xs text-muted-foreground">{symbols.isFetching ? "Searching symbols…" : `No results for “${q}”`}</li>}
          {cmds.map((c, i) => {
            const header = c.group !== last ? (last = c.group) : null;
            return (
              <li key={c.id} role="presentation">
                {header && <div className="px-2.5 pb-1 pt-2 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground/80">{header}</div>}
                <button id={`cmd-${i}`} data-i={i} role="option" aria-selected={i === sel} onMouseMove={() => setSel(i)} onClick={() => run(c)}
                  className={cn("flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[13px]", i === sel ? "bg-accent" : "")}>
                  <span className="text-muted-foreground">{c.icon}</span><span className="truncate">{c.label}</span>{c.hint && <span className="ml-auto max-w-[55%] truncate text-xs text-muted-foreground">{c.hint}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
