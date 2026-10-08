import type { Edit, Proposal } from "./types";

/** Mirrors the backend rule (app/patching.py): `search` must occur exactly once, replaced in order. */
export function applyEdits(original: string, edits: Edit[]): { text: string; conflicts: number[] } {
  let text = original;
  const conflicts: number[] = [];
  edits.forEach((e, i) => {
    const count = e.search ? text.split(e.search).length - 1 : 0;
    if (count !== 1) { conflicts.push(i); return; }
    text = text.replace(e.search, () => e.replace ?? "");
  });
  return { text, conflicts };
}

/** 1-based line where an edit starts in `text`, or 1. */
export function lineOf(text: string, needle: string): number {
  const i = text.indexOf(needle);
  return i < 0 ? 1 : text.slice(0, i).split("\n").length;
}

export const editKey = (i: number) => `e:${i}`;
export const newKey = (path: string) => `n:${path}`;

export function filesOf(p: Proposal): string[] {
  return [...new Set([...p.edits.map((e) => e.file), ...p.newFiles.map((n) => n.path)])];
}

export function counts(p: Proposal) {
  const keys = [...p.edits.map((_, i) => editKey(i)), ...p.newFiles.map((n) => newKey(n.path))];
  const by = (d: string) => keys.filter((k) => p.decisions[k] === d).length;
  return { total: keys.length, accepted: by("accepted"), rejected: by("rejected"), pending: by("pending") };
}
