import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const basename = (p: string) => p.split("/").pop() ?? p;
export const dirname = (p: string) => (p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "");

/** "12-30" -> [12, 30] */
export function parseLines(lines: string | number | undefined): [number, number] {
  if (typeof lines === "number") return [lines, lines];
  const m = /^(\d+)(?:-(\d+))?$/.exec(String(lines ?? ""));
  if (!m) return [1, 1];
  const a = Number(m[1]);
  return [a, m[2] ? Number(m[2]) : a];
}

/** Subsequence fuzzy score: higher is better, -1 means no match. */
export function fuzzy(query: string, text: string): number {
  if (!query) return 0;
  const q = query.toLowerCase(), t = text.toLowerCase();
  let qi = 0, score = 0, last = -2;
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) {
      score += i === last + 1 ? 3 : 1;
      if (i === 0 || "/._-".includes(t[i - 1])) score += 2;
      last = i;
      qi++;
    }
  }
  if (qi < q.length) return -1;
  return score - t.length * 0.01;
}

export const fmtMs = (ms?: number) => (ms == null ? "" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
export const uid = () => Math.random().toString(36).slice(2, 10);
