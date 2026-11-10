"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UiState { collapsed: boolean; setCollapsed: (v: boolean) => void; mobileNav: boolean; setMobileNav: (v: boolean) => void; palette: boolean; setPalette: (v: boolean) => void; addProject: boolean; setAddProject: (v: boolean) => void }

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      collapsed: false, setCollapsed: (collapsed) => set({ collapsed }),
      mobileNav: false, setMobileNav: (mobileNav) => set({ mobileNav }),
      palette: false, setPalette: (palette) => set({ palette }),
      addProject: false, setAddProject: (addProject) => set({ addProject }),
    }),
    { name: "codebase-agent-ui", partialize: (s) => ({ collapsed: s.collapsed }), skipHydration: true },
  ),
);
