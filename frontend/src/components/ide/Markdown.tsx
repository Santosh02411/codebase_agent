"use client";
import { isValidElement } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

export function DiffBlock({ text }: { text: string }) {
  return (
    <pre className="overflow-x-auto rounded-md border bg-background p-2 font-mono text-[11px] leading-snug">
      {text.replace(/\n$/, "").split("\n").map((l, i) => (
        <div key={i} className={cn(l.startsWith("+") && !l.startsWith("+++") && "bg-emerald-500/10 text-emerald-300", l.startsWith("-") && !l.startsWith("---") && "bg-red-500/10 text-red-300", l.startsWith("@@") && "text-sky-300")}>{l || " "}</div>
      ))}
    </pre>
  );
}

export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
          pre: ({ children }) => {
            const child = Array.isArray(children) ? children[0] : children;
            if (isValidElement<{ className?: string; children?: React.ReactNode }>(child)) {
              const lang = /language-(\w+)/.exec(child.props.className ?? "")?.[1];
              const text = String(child.props.children ?? "");
              if (lang === "diff") return <DiffBlock text={text} />;
              return <pre className="overflow-x-auto rounded-md border bg-background p-2 font-mono text-[11px] leading-snug">{text.replace(/\n$/, "")}</pre>;
            }
            return <pre>{children}</pre>;
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
