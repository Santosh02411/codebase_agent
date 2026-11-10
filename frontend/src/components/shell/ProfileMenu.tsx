"use client";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Github, LogIn, LogOut, Settings, User } from "lucide-react";
import { toast } from "sonner";
import { API_URL, api } from "@/lib/api";
import { useAuthStatus } from "@/hooks/queries";
import { Dropdown, DropdownContent, DropdownItem, DropdownLabel, DropdownSeparator, DropdownTrigger } from "@/components/ui/dropdown";

export function ProfileMenu() {
  const router = useRouter();
  const auth = useAuthStatus();
  const qc = useQueryClient();
  const gh = auth.data?.github;
  const logout = useMutation({ mutationFn: api.githubLogout, onSuccess: () => { qc.invalidateQueries({ queryKey: ["auth"] }); toast.success("Disconnected from GitHub"); } });
  const user = gh?.user;
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <button aria-label="Account" className="flex size-8 items-center justify-center overflow-hidden rounded-full bg-secondary text-muted-foreground ring-1 ring-border hover:ring-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {user?.avatar ? <img src={user.avatar} alt="" className="size-full object-cover" /> : <User className="size-4" />}
        </button>
      </DropdownTrigger>
      <DropdownContent className="w-60">
        <div className="px-2 py-2"><div className="text-[13px] font-medium">{user ? user.name || user.login : "Local user"}</div><div className="text-xs text-muted-foreground">{user ? `@${user.login} · GitHub connected` : "Not signed in to GitHub"}</div></div>
        <DropdownSeparator />
        {user ? <DropdownItem icon={<LogOut />} onSelect={() => logout.mutate()}>Disconnect GitHub</DropdownItem>
          : gh?.oauth_configured ? <DropdownItem icon={<LogIn />} onSelect={() => { window.location.href = api.githubLoginUrl(); }}>Sign in with GitHub</DropdownItem>
          : <DropdownItem icon={<Github />} disabled>GitHub sign-in not configured</DropdownItem>}
        <DropdownItem icon={<Settings />} onSelect={() => router.push("/settings")}>Settings</DropdownItem>
        <DropdownSeparator />
        <DropdownLabel className="normal-case tracking-normal">API: {API_URL || "same origin (this server)"}</DropdownLabel>
      </DropdownContent>
    </Dropdown>
  );
}
