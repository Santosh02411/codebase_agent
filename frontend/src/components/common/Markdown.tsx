"use client";
import { isValidElement, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { CopyButton, FileLink } from "./bits";
import type { Source } from "@/lib/types";
import { parseLines } from "@/lib/utils";

const FILE_REF = /(?<![\w/.\-@])((?:[\w.\-]+\/)*[\w.\-]+\.(?:py|js|jsx|mjs|ts|tsx|java|go|rs|c|cc|cpp|h|hpp|cs|rb|php|kt|swift|sql|ya?ml|json|toml|md))(?::(\d{1,6})(?:-(\d{1,6}))?)?(?![\w/])/g;
const CITE = /\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\()/g;

/** Turn `[2]` citations and `path/file.py:12` references into links the renderer understands (cite:2 / file:path#12-14). Code is left alone. */
export function linkify(text: string, hasSources: boolean): string {
  return text.split(/(```[\s\S]*?```|`[^`\n]*`)/g).map((seg, i) => {
    if (i % 2 === 1) return seg;
    let out = seg;
    if (hasSources) out = out.replace(CITE, (_m, nums: string) => nums.split(/\s*,\s*/).map((n) => `[${n}](cite:${n})`).join(""));
    return out.replace(FILE_REF, (m, path: string, a?: string, b?: string) => (/^\d+(\.\d+)+$/.test(path) ? m : `[${m}](file:${encodeURIComponent(path)}#${a ?? ""}-${b ?? ""})`));
  }).join("");
}

export function DiffBlock({ text }: { text: string }) {
  return (
    <pre className="overflow-x-auto rounded-lg border bg-surface p-2.5 font-mono text-[12px] leading-relaxed">
      {text.replace(/\n$/, "").split("\n").map((l, i) => (
        <div key={i} className={cn("px-1", l.startsWith("+") && !l.startsWith("+++") && "bg-success/10 text-success", l.startsWith("-") && !l.startsWith("---") && "bg-destructive/10 text-destructive", l.startsWith("@@") && "text-info")}>{l || " "}</div>
      ))}
    </pre>
  );
}

/** Model output can contain repository-derived text, so only safe link targets survive: web links, mailto, our own cite:/file: links and in-page anchors. */
const safeUrl = (url: string) => (/^(https?:|mailto:|cite:|file:|#)/i.test(url) ? url : "");

function textOf(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: React.ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

export function Markdown({ children, sources, onCite }: { children: string; sources?: Source[]; onCite?: (n: number) => void }) {
  const md = useMemo(() => linkify(children, !!sources?.length), [children, sources]);
  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: false, ignoreMissing: true }]]}
        urlTransform={safeUrl}
        components={{
          a: ({ href = "", children }) => {
            if (href.startsWith("cite:")) {
              const n = Number(href.slice(5));
              const src = sources?.find((s) => s.cite === n) ?? sources?.[n - 1];
              if (!src) return <span className="text-muted-foreground">[{n}]</span>;
              const [a, b] = parseLines(src.lines);
              return <button type="button" onClick={() => onCite?.(n)} title={`${src.file}:${src.lines}${src.symbol ? ` · ${src.symbol}` : ""}`} data-file={src.file} data-line={a} data-end={b}
                className="mx-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded bg-primary/12 px-1 align-baseline text-[11px] font-semibold text-primary hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60">{n}</button>;
            }
            if (href.startsWith("file:")) {
              const [enc, range = ""] = href.slice(5).split("#");
              const [a, b] = range.split("-");
              return <FileLink path={decodeURIComponent(enc)} line={a ? Number(a) : undefined} end={b ? Number(b) : undefined}>{children}</FileLink>;
            }
            return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
          },
          code: ({ className, children, ...p }) => {
            const t = textOf(children).trim();
            if (!className && !t.includes("\n")) {
              const m = /^((?:[\w.\-]+\/)*[\w.\-]+\.[A-Za-z]{1,5})(?::(\d+)(?:-(\d+))?)?$/.exec(t);
              if (m && !/^\d+\.\d+/.test(m[1]) && /\.(py|js|jsx|ts|tsx|java|go|rs|c|cpp|h|cs|rb|php|kt|sql|ya?ml|json|toml|md)$/.test(m[1])) return <FileLink path={m[1]} line={m[2] ? Number(m[2]) : undefined} end={m[3] ? Number(m[3]) : undefined} />;
            }
            return <code className={className} {...p}>{children}</code>;
          },
          pre: ({ children }) => {
            const child = Array.isArray(children) ? children[0] : children;
            if (isValidElement<{ className?: string; children?: React.ReactNode }>(child)) {
              const lang = /language-([\w-]+)/.exec(child.props.className ?? "")?.[1] ?? "";
              const raw = textOf(child.props.children).replace(/\n$/, "");
              if (lang === "diff") return <DiffBlock text={raw} />;
              return (
                <div className="group my-1 overflow-hidden rounded-lg border bg-surface">
                  <div className="flex items-center justify-between border-b bg-muted/60 px-3 py-1"><span className="font-mono text-[11px] text-muted-foreground">{lang || "text"}</span><CopyButton text={raw} label="Copy code" /></div>
                  <pre className="overflow-x-auto p-3 font-mono text-[12.5px] leading-relaxed">{child}</pre>
                </div>
              );
            }
            return <pre>{children}</pre>;
          },
        }}
      >
        {md}
      </ReactMarkdown>
    </div>
  );
}
