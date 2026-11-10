"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemePref = "light" | "dark" | "system";
export type Theme = "light" | "dark";

/** Resolved theme for the current preference (system follows the OS setting). */
export const resolveTheme = (pref: ThemePref): Theme =>
  pref === "system" ? (typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : pref;

/** Applies the theme to <html>. `animate` adds a short-lived class that makes colours transition smoothly. */
export function applyTheme(pref: ThemePref, animate = false): Theme {
  const t = resolveTheme(pref);
  const el = document.documentElement;
  if (animate) { el.classList.add("theme-anim"); window.setTimeout(() => el.classList.remove("theme-anim"), 320); }
  el.classList.toggle("dark", t === "dark");
  el.style.colorScheme = t;
  return t;
}

interface ThemeState { pref: ThemePref; theme: Theme; setPref: (p: ThemePref) => void; sync: () => void }

export const useTheme = create<ThemeState>()(
  persist(
    (set, get) => ({
      pref: "system", theme: "dark",
      setPref: (pref) => set({ pref, theme: applyTheme(pref, true) }),
      sync: () => set({ theme: applyTheme(get().pref) }),
    }),
    { name: "codebase-agent-theme", partialize: (s) => ({ pref: s.pref }), skipHydration: true, onRehydrateStorage: () => (s) => { s?.sync(); } },
  ),
);

/** Runs before first paint (inlined in <head>) so there is no flash of the wrong theme. */
export const THEME_SCRIPT = `(function(){try{var s=JSON.parse(localStorage.getItem("codebase-agent-theme")||"{}");var p=(s.state&&s.state.pref)||"system";var d=p==="dark"||(p==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);var e=document.documentElement;e.classList.toggle("dark",d);e.style.colorScheme=d?"dark":"light"}catch(_){document.documentElement.classList.add("dark")}})();`;
