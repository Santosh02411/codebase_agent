"use client";
import { ChatPage } from "@/components/chat/ChatPage";
import { RequireProject } from "@/components/shell/RequireProject";

export default function Page() {
  return <RequireProject>{(id) => <ChatPage repoId={id} />}</RequireProject>;
}
