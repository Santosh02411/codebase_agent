"use client";
import { useTheme } from "@/lib/theme";

/** Monaco theme name that follows the app theme (editor, diff editor and read-only viewers). */
export const useMonacoTheme = () => useTheme((s) => (s.theme === "dark" ? "vs-dark" : "vs"));
