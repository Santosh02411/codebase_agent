import { Bug, FlaskConical, FolderTree, GitPullRequest, LayoutDashboard, MessagesSquare, Network, ScanSearch, Settings, ShieldCheck, FileDiff } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem { href: string; label: string; icon: LucideIcon; group: "workspace" | "analyze" | "ship" | "system"; hint: string }

export const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, group: "workspace", hint: "Project overview" },
  { href: "/review", label: "Code Review", icon: ScanSearch, group: "workspace", hint: "Find real errors in every file, in seconds" },
  { href: "/chat", label: "AI Chat", icon: MessagesSquare, group: "workspace", hint: "Ask, debug, review, change, test" },
  { href: "/explorer", label: "Code Explorer", icon: FolderTree, group: "workspace", hint: "Files, symbols, references" },
  { href: "/architecture", label: "Architecture", icon: Network, group: "analyze", hint: "System map, execution flow, structure, 3D" },
  { href: "/debug", label: "Debugging", icon: Bug, group: "analyze", hint: "Root cause and verified fixes" },
  { href: "/quality", label: "Code Quality", icon: ShieldCheck, group: "analyze", hint: "Score, analyzers, trends" },
  { href: "/changes", label: "Changes & Patches", icon: FileDiff, group: "ship", hint: "Review, apply, revert" },
  { href: "/testing", label: "Testing", icon: FlaskConical, group: "ship", hint: "Runs, logs, coverage" },
  { href: "/github", label: "GitHub & PRs", icon: GitPullRequest, group: "ship", hint: "Pull requests, issues, approvals" },
  { href: "/settings", label: "Settings", icon: Settings, group: "system", hint: "Providers, sandbox, appearance" },
];
export const GROUPS: Record<NavItem["group"], string> = { workspace: "Workspace", analyze: "Analyze", ship: "Ship", system: "System" };
