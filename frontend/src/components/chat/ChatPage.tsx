"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, Eraser, Sparkles } from "lucide-react";
import { useAgentRun } from "@/hooks/useAgentRun";
import { useIde } from "@/store/ide";
import type { ChatMessage, Mode } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { AgentTimeline } from "./AgentTimeline";
import { Composer } from "./Composer";
import { MessageList } from "./Messages";
import { MODES } from "./modes";
import { cn } from "@/lib/utils";

function Welcome() {
  const setMode = useIde((s) => s.setMode);
  const mode = useIde((s) => s.mode);
  return (
    <div className="mx-auto flex max-w-3xl flex-col items-center gap-6 px-4 pb-4 pt-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary"><Sparkles className="size-6" /></div>
      <div><h1 className="text-xl font-semibold">What do you want to do with this codebase?</h1><p className="mt-1 text-[13px] text-muted-foreground">Pick a mode, then ask. Every run shows the real phases, tools and evidence on the right.</p></div>
      <div className="grid w-full gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {MODES.map((m) => (
          <button key={m.mode} onClick={() => { setMode(m.mode); window.dispatchEvent(new Event("agent:focus-chat")); }} className={cn("rounded-xl bg-panel p-3.5 text-left shadow-card transition-all hover:-translate-y-0.5 hover:shadow-pop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60", mode === m.mode && "ring-2 ring-primary/40")}>
            <span className="flex items-center gap-2 text-[13px] font-medium"><m.icon className="size-4 text-primary" />{m.label}</span><span className="mt-1 block text-xs leading-relaxed text-muted-foreground">{m.blurb}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function ChatPage({ repoId }: { repoId: string }) {
  const { run, stop } = useAgentRun();
  const messages = useIde((s) => s.messages);
  const runs = useIde((s) => s.runs);
  const activeRunId = useIde((s) => s.activeRunId);
  const setActiveRun = useIde((s) => s.setActiveRun);
  const resetChat = useIde((s) => s.resetChat);
  const [drawer, setDrawer] = useState(false);
  const router = useRouter();
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const running = runs.some((r) => r.state === "running");
  const lastRun = runs[runs.length - 1];

  // "Ask AI" from the editor: the selection is already attached; just make sure this page is showing.
  useEffect(() => { const f = () => router.push("/chat"); window.addEventListener("agent:ask-selection", f); return () => window.removeEventListener("agent:ask-selection", f); }, [router]);
  // keep the newest content in view unless the reader scrolled up
  useEffect(() => { const el = scroller.current; if (el && stick.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" }); }, [messages, lastRun?.events.length]);

  const send = (mode: Mode, text: string, target?: string) => { stick.current = true; void run(mode, text, { target }); };
  const retry = (m: ChatMessage) => {
    const i = messages.findIndex((x) => x.id === m.id);
    const q = [...messages.slice(0, i)].reverse().find((x) => x.role === "user");
    if (q) send(q.mode, q.text);
  };

  return (
    <div className="flex h-full min-h-0">
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Conversation">
        <div className="flex h-11 shrink-0 items-center justify-between border-b px-4">
          <div className="flex items-center gap-2 text-[13px] font-medium"><Sparkles className="size-4 text-primary" />AI Chat</div>
          <div className="flex items-center gap-1.5">
            <Button size="sm" variant="ghost" className="xl:hidden" onClick={() => setDrawer(true)}><Activity />{running ? "Agent working…" : "Activity"}</Button>
            <Button size="sm" variant="ghost" disabled={running || messages.length === 0} onClick={() => resetChat()}><Eraser />New chat</Button>
          </div>
        </div>
        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto" onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
          {messages.length === 0 ? <Welcome /> : <MessageList messages={messages} runs={runs} onRetry={retry} />}
        </div>
        <div className="shrink-0 border-t bg-background/80 px-4 py-3 backdrop-blur"><div className="mx-auto max-w-3xl"><Composer repoId={repoId} running={running} onSend={send} onStop={stop} showSuggestions={messages.length === 0} /></div></div>
      </section>
      <aside className="hidden w-[340px] shrink-0 border-l bg-panel xl:block" aria-label="Agent activity"><AgentTimeline runs={runs} activeId={activeRunId} onSelect={setActiveRun} /></aside>
      <Drawer open={drawer} onOpenChange={setDrawer} title="Agent activity" description="Real phases, tools and timings of the selected run"><AgentTimeline runs={runs} activeId={activeRunId} onSelect={setActiveRun} /></Drawer>
    </div>
  );
}
