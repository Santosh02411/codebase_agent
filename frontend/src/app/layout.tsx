import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { THEME_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  title: "CodeScout AI: AI-Powered Automated Code Review",
  description: "Find real bugs, typos, wrong imports and security problems in your code in seconds, then fix them with an AI agent you can watch working.",
};
export const viewport: Viewport = { themeColor: [{ media: "(prefers-color-scheme: dark)", color: "#0e0f13" }, { media: "(prefers-color-scheme: light)", color: "#f6f7f9" }] };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} /></head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
