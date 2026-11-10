"use client";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme, type ThemePref } from "@/lib/theme";
import { Button } from "@/components/ui/button";
import { Dropdown, DropdownContent, DropdownItem, DropdownLabel, DropdownTrigger } from "@/components/ui/dropdown";

const OPTS: { v: ThemePref; label: string; icon: React.ReactNode }[] = [
  { v: "light", label: "Light", icon: <Sun /> }, { v: "dark", label: "Dark", icon: <Moon /> }, { v: "system", label: "System", icon: <Monitor /> },
];

export function ThemeMenu() {
  const pref = useTheme((s) => s.pref);
  const theme = useTheme((s) => s.theme);
  const setPref = useTheme((s) => s.setPref);
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Theme: ${pref}`}>{theme === "dark" ? <Moon /> : <Sun />}</Button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Appearance</DropdownLabel>
        {OPTS.map((o) => <DropdownItem key={o.v} icon={o.icon} checked={pref === o.v} onSelect={() => setPref(o.v)}>{o.label}</DropdownItem>)}
      </DropdownContent>
    </Dropdown>
  );
}
