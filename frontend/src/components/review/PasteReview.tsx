"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CircleCheck, Play, Wand2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/states";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Item } from "./ReviewPage";

const EXAMPLES: Record<string, { file: string; code: string }> = {
  python: { file: "demo.py", code: `import os, sys

class Order:
    def __init__(self, name, total):
        self.name = name
        self.total = total

    def label(self):
        return self.nmae + str(self.total)


def total(items):
    s = 0
    for item in itmes:
        s += item.price
    return s / 0


def make(a, b):
    return a + b


path = os.pth.join("a", "b")
make(1, 2, 3)
if total([]) == None:
    print(retrun_value)
` },
  javascript: { file: "demo.jsx", code: `import { useState } from 'react'

export default function Counter() {
  const [count, setCount] = useSate(0)
  if (count = 5) {
    console.log("five")
  }
  return (
    <div>
      <Hedaer title="Counter" />
      <button onClick={() => { setCount(count + 1 }>Add</button>
    </div>
  )
}
` },
};

/** Review code pasted into the page: no project needed. Imports between project files cannot be checked here (there is no project). */
export function PasteReview() {
  const [lang, setLang] = useState("python");
  const [file, setFile] = useState(EXAMPLES.python.file);
  const [code, setCode] = useState("");
  const run = useMutation({ mutationFn: () => api.reviewSnippet(file, code) });
  const r = run.data;
  const load = (l: string) => { setLang(l); setFile(EXAMPLES[l].file); setCode(EXAMPLES[l].code); run.reset(); };
  return (
    <div className="space-y-4">
      <Card><CardBody className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">File name (decides the language):</span>
          <input value={file} onChange={(e) => setFile(e.target.value)} aria-label="File name" className="h-8 w-44 rounded-md border border-input bg-panel px-2.5 font-mono text-[13px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" />
          <Select aria-label="Load an example" className="h-8 w-44 text-xs" value={lang} onValueChange={load} options={[{ value: "python", label: "Example: Python with mistakes" }, { value: "javascript", label: "Example: React with mistakes" }]} />
          <Button size="sm" variant="outline" onClick={() => load(lang)}><Wand2 />Load example</Button>
          <Button size="sm" className="ml-auto" onClick={() => run.mutate()} loading={run.isPending} disabled={!code.trim()}><Play />Review this code</Button>
        </div>
        <Textarea value={code} onChange={(e) => setCode(e.target.value)} rows={16} spellCheck={false} aria-label="Code to review" placeholder="Paste Python, JavaScript/TypeScript/JSX, Java, Go, Rust, C/C++, JSON, YAML, TOML, HTML or CSS here…" className="font-mono text-[12.5px] leading-relaxed" />
        <p className="text-xs text-muted-foreground">Checks that need other files (imports between your project’s files) are skipped for pasted code. Import the project to get those.</p>
      </CardBody></Card>
      {run.isError && <ErrorState title="The review could not run" error={run.error} />}
      {r && (
        <Card>
          <CardBody className="space-y-3">
            <div className="flex items-center gap-2 text-[13px] font-semibold">{r.summary.total === 0 ? <><CircleCheck className="size-5 text-success" />No problems found</> : <>{r.summary.total} finding{r.summary.total === 1 ? "" : "s"}</>}
              <Badge variant="outline">{r.duration_ms} ms</Badge>{r.summary.by_severity.high ? <Badge variant="destructive">{r.summary.by_severity.high} high</Badge> : null}{r.summary.by_severity.medium ? <Badge variant="warning">{r.summary.by_severity.medium} medium</Badge> : null}</div>
          </CardBody>
          {r.findings.length > 0 && <ul className="border-t">{r.findings.map((f, i) => <Item key={f.id + i} f={f} defaultOpen={i === 0} />)}</ul>}
          {r.coverage.skipped.length > 0 && <p className="border-t px-4 py-3 text-xs text-muted-foreground">{r.coverage.skipped[0].reason}</p>}
        </Card>
      )}
    </div>
  );
}
