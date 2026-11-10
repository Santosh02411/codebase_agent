import { Bug, FlaskConical, MessageCircleQuestion, ScanSearch, Wand2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Insights, Mode, RepoStats } from "@/lib/types";

export interface ModeDef { mode: Mode; label: string; icon: LucideIcon; blurb: string; placeholder: string; needsVerify: boolean; fallback: string[] }

export const MODES: ModeDef[] = [
  { mode: "chat", label: "Explain", icon: MessageCircleQuestion, blurb: "Ask how the code works. Answers cite the code they rely on.", placeholder: "Ask about the code…  (@ to reference a file or symbol)", needsVerify: false,
    fallback: ["Give me an overview of how this project is structured", "Where is configuration loaded and used?", "How is error handling done across the code?"] },
  { mode: "debug", label: "Debug", icon: Bug, blurb: "Paste an error or describe a bug. Finds the root cause and proposes a fix, verified by tests when possible.", placeholder: "Paste a stack trace, error message or describe the bug…", needsVerify: true,
    fallback: ["The tests are failing. Find the cause and fix it", "I get a 500 error. Here is the traceback: ", "Something returns None unexpectedly. Find out why"] },
  { mode: "review", label: "Review", icon: ScanSearch, blurb: "Review the project or a file for bugs, security problems and maintainability.", placeholder: "What should be reviewed?  (@file to review one file)", needsVerify: false,
    fallback: ["Review this project for bugs and security problems", "Review error handling and input validation", "Look for hard-coded secrets and unsafe calls"] },
  { mode: "change", label: "Change", icon: Wand2, blurb: "Describe a change. The agent edits across files and tests before and after. Nothing is applied until you approve.", placeholder: "Describe the change you want…", needsVerify: true,
    fallback: ["Add input validation to the main request handler", "Add logging around the main entry points", "Refactor the longest function into smaller ones"] },
  { mode: "tests", label: "Test", icon: FlaskConical, blurb: "Write tests in your repository’s own style and run them.", placeholder: "Which code needs tests?  (@file to target one file)", needsVerify: true,
    fallback: ["Write tests for the least-tested module", "Add edge-case tests for input validation", "Write a regression test for the last bug fix"] },
];

/** Suggestions built from the project's own routes, models and tests; generic ones only when the project has none. */
export function suggestionsFor(mode: Mode, stats?: RepoStats, ins?: Insights): { items: string[]; derived: boolean } {
  const fromCode = (ins?.suggested_questions ?? []).filter((q) => (mode === "review" ? q.mode === "review" : mode === "chat" ? q.mode === "chat" : false)).map((q) => q.question);
  const hub = ins?.hubs[0], route = ins?.routes[0], untested = ins?.risks.untested_modules[0];
  const own: string[] = [...fromCode];
  if (mode === "debug") { if (route) own.push(`${route.method} ${route.path} returns an error. Find the root cause`); if (hub) own.push(`\`${hub.qualname}\` returns something unexpected. Why?`); }
  if (mode === "change") { if (route) own.push(`Add input validation to ${route.method} ${route.path}`); if (hub) own.push(`Add logging to \`${hub.qualname}\``); }
  if (mode === "tests") { if (untested) own.push(`Write tests for \`${untested}\`. No test reaches it today`); if (route) own.push(`Write tests for ${route.method} ${route.path}`); }
  if (own.length) return { items: own.slice(0, 4), derived: true };
  return { items: legacySuggestions(mode, stats), derived: false };
}

function legacySuggestions(mode: Mode, stats?: RepoStats): string[] {
  const def = MODES.find((m) => m.mode === mode) ?? MODES[0];
  const api = stats?.apis.items[0], model = stats?.models[0];
  const own: string[] = [];
  if (mode === "chat") { if (api) own.push(`How does ${api.method} ${api.path} work, end to end?`); if (model) own.push(`Explain the ${model.name} model and where it is used`); }
  if (mode === "debug" && api) own.push(`${api.method} ${api.path} returns an error. Find the root cause`);
  if (mode === "review" && api) own.push(`Review the handler for ${api.method} ${api.path}`);
  if (mode === "change" && api) own.push(`Add validation to ${api.method} ${api.path}`);
  if (mode === "tests" && api) own.push(`Write tests for ${api.method} ${api.path}`);
  return [...own, ...def.fallback].slice(0, 4);
}
