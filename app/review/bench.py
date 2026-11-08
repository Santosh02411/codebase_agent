"""Benchmark of the strict review engine: seeded mistakes (does it find them, on the right line?) and clean code (does it stay quiet?).

Run `python -m app.review.bench [--corpus PATH ...]`. The cases are written by hand from mistakes people really make; they are a regression suite and an honest
yardstick for THIS engine, not a claim about other tools or about every bug in the world. Clean-code false-positive counts come from running the engine over
folders you pass in (for example this repository's own source)."""
from __future__ import annotations
import argparse
import json
import tempfile
import time
from pathlib import Path

from .engine import review_project

PKG = '{"name":"app","dependencies":{"react":"^19","react-dom":"^19"}}'
HEADER = "export default function Header({ title }) {\n  return <h1>{title}</h1>\n}\nexport const Logo = () => <i />\n"
ETA = "DEFAULT = 30\n\n\ndef calculate_eta(distance_km, speed_kmh=None):\n    speed = speed_kmh or DEFAULT\n    return round(distance_km / speed * 60)\n"


def py(name, code, rule, line, extra=None):
    return {"name": name, "category": "Python", "files": {"m.py": code, **(extra or {})}, "expect": ("m.py", rule, line)}


def js(name, code, rule, line, file="src/A.jsx"):
    return {"name": name, "category": "JavaScript / React", "files": {"package.json": PKG, "src/Header.jsx": HEADER, file: code}, "expect": (file, rule, line)}


def data(name, fname, code, rule, line):
    return {"name": name, "category": "Data & markup", "files": {fname: code}, "expect": (fname, rule, line)}


CASES = [
    # ---- Python: syntax --------------------------------------------------------------------------------------------------------
    py("missing colon after def", "def f(x)\n    return x\n", "PY-SYNTAX", 1),
    py("unclosed parenthesis", "def f(x):\n    return (x + 1\n", "PY-SYNTAX", 2),
    py("extra closing parenthesis", "def f(x):\n    return x)\n", "PY-SYNTAX", 2),
    py("misspelled keyword (retrun)", "def f(x):\n    retrun x\n", "PY-SYNTAX", 2),
    py("bad indentation", "def f(x):\n  y = 1\n    return y\n", "PY-SYNTAX", 3),
    py("unterminated string", "s = 'abc\n", "PY-SYNTAX", 1),
    py("missing comma in call", "print('a' 'b' x)\n", "PY-SYNTAX", 1),
    # ---- Python: names and typos -----------------------------------------------------------------------------------------------
    py("undefined variable", "def total(items):\n    return summ\n", "PY-UNDEFINED", 2),
    py("misspelled loop variable", "def total(items):\n    s = 0\n    for i in itmes:\n        s += i\n    return s\n", "PY-UNDEFINED", 3),
    py("misspelled function call", "def compute(x):\n    return x\n\n\nresult = comptue(3)\n", "PY-UNDEFINED", 5),
    py("Python 2 leftover (xrange)", "for i in xrange(3):\n    print(i)\n", "PY-UNDEFINED", 1),
    py("self attribute typo", "class A:\n    def __init__(self):\n        self.name = 1\n    def g(self):\n        return self.nmae\n", "PY-ATTR", 5),
    py("stdlib attribute typo", "import os\nx = os.pth.join('a')\n", "PY-MODATTR", 2),
    py("math function typo", "import math\ny = math.sqroot(4)\n", "PY-MODATTR", 2),
    # ---- Python: imports and calls ---------------------------------------------------------------------------------------------
    py("import of a name that does not exist", "from services.eta import calculate_etaa\n", "PY-IMPORT", 1, {"services/eta.py": ETA, "services/__init__.py": ""}),
    py("import of a module that does not exist", "from services.etaa import x\n", "PY-IMPORT", 1, {"services/eta.py": ETA, "services/__init__.py": ""}),
    py("too many arguments", "def f(a, b):\n    return a\n\n\nf(1, 2, 3)\n", "PY-ARITY", 5),
    py("missing argument", "def f(a, b):\n    return a\n\n\nf(1)\n", "PY-ARITY", 5),
    py("misspelled keyword argument", "def f(speed):\n    return speed\n\n\nf(spped=3)\n", "PY-ARITY", 5),
    py("wrong arity across files", "from services.eta import calculate_eta\n\n\ncalculate_eta(1, 2, 3)\n", "PY-ARITY", 4, {"services/eta.py": ETA, "services/__init__.py": ""}),
    py("self method called without argument", "class A:\n    def pay(self, amount):\n        return amount\n    def run(self):\n        return self.pay()\n", "PY-ARITY", 5),
    py("method without self", "class A:\n    def g():\n        return 1\n", "PY-NOSELF", 2),
    # ---- Python: bug patterns --------------------------------------------------------------------------------------------------
    py("division by literal zero", "def f():\n    return 1 / 0\n", "PY-DIVZERO", 2),
    py("assert on a tuple", "def f(items):\n    assert (items, 'empty')\n", "PY-ASSERT", 2),
    py("string plus number", "x = 'a' + 1\n", "PY-TYPEMIX", 1),
    py("mutable default argument", "def f(x=[]):\n    return x\n", "PY-MUTDEF", 1),
    py("function defined twice", "def a():\n    return 1\n\n\ndef a():\n    return 2\n", "PY-REDEF", 5),
    py("unreachable code", "def f():\n    return 1\n    print('never')\n", "PY-UNREACHABLE", 3),
    py("duplicate dict key", "d = {'a': 1, 'a': 2}\n", "PY-DUPKEY", 1),
    py("format placeholder count", "x = 'a %s %s' % (1,)\n", "PY-FORMAT", 1),
    py("is with a literal", "def f(x):\n    return x is 'a'\n", "PY-ISLIT", 2),
    py("bare except", "try:\n    x = 1\nexcept:\n    pass\n", "PY-BAREEXCEPT", 3),
    # ---- Python: security ------------------------------------------------------------------------------------------------------
    py("shell=True", "import subprocess\nsubprocess.run('ls', shell=True)\n", "PY-SHELL", 2),
    py("SQL injection by concatenation", "def q(c, n):\n    c.execute(\"SELECT * FROM t WHERE n = '\" + n + \"'\")\n", "PY-SQLI", 2),
    py("yaml.load without a loader", "import yaml\nd = yaml.load(open('x'))\n", "PY-YAML", 2),
    py("hard-coded password", "password = 'hunter2hunter2'\n", "SECRET", 1),
    py("hard-coded API token in a class", "class Config:\n    API_TOKEN = 'ghp_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8'\n", "SECRET", 2),
    py("TLS verification disabled", "import requests\nrequests.get('https://x', verify=False)\n", "PY-TLS", 2),
    # ---- JavaScript / React ----------------------------------------------------------------------------------------------------
    js("import path typo", "import Header from './Hedaer'\nexport default function A() { return <Header /> }\n", "JS-IMPORT", 1),
    js("name that the module does not export", "import Header, { Banner } from './Header'\nexport default function A() { return <Header><Banner /></Header> }\n", "JS-EXPORT", 1),
    js("package name typo", "import React from 'reactt'\nexport default function A() { return <div /> }\n", "JS-PACKAGE", 1),
    js("misspelled component", "import Header from './Header'\nexport default function A() { return <Hedaer title='x' /> }\n", "JS-UNDEFINED", 2),
    js("hook used without import", "export default function A() { const [a, b] = useState(0); return <div>{a}{b}</div> }\n", "JS-UNDEFINED", 1),
    js("misspelled variable in JSX", "import { useState } from 'react'\nexport default function A() { const [name, setName] = useState(''); return <input value={nmae} onChange={() => setName('')} /> }\n", "JS-UNDEFINED", 2),
    js("unclosed JSX expression", "export default function A() {\n  return <button onClick={() => { go() }>Go</button>\n}\n", "JS-SYNTAX", 2),
    js("extra closing brace", "export default function A() {\n  return 1\n}\n}\n", "JS-SYNTAX", 4),
    js("missing closing brace", "export default function A() {\n  return 1\n", "JS-SYNTAX", 3),
    js("assignment inside a condition", "export function f(x) {\n  if (x = 1) {\n    return 2\n  }\n  return 3\n}\n", "JS-ASSIGNCOND", 2),
    js("empty catch", "export function f() {\n  try { go() } catch (e) {}\n}\nfunction go() {}\n", "JS-EMPTYCATCH", 2),
    js("debugger left in", "export function f() {\n  debugger\n  return 1\n}\n", "JS-DEBUGGER", 2),
    # ---- data and markup -------------------------------------------------------------------------------------------------------
    data("trailing comma in JSON", "d.json", '{"a": 1,}\n', "JSON-SYNTAX", 1),
    data("unclosed HTML tag", "i.html", "<div><span>x</div>\n", "HTML-UNCLOSED", 1),
    data("bad YAML indentation", "c.yaml", "a:\n  b: 1\n c: 2\n", "YAML-SYNTAX", 3),
    data("unclosed CSS rule", "s.css", "a { color: red;\n", "BRACE", 1),
]

CLEAN = [
    ("valid Python with classes, closures and comprehensions", {"m.py": "import os\nfrom typing import List\n\n\nclass A:\n    x = 1\n\n    def g(self, items: 'List[int]'):\n        total = sum(i for i in items)\n        def inner():\n            nonlocal total\n            total += 1\n        inner()\n        return total + self.x + len(os.sep)\n"}),
    ("constants named like secrets that are not secrets", {"m.py": "TOKEN_URL = 'https://github.com/login/oauth/access_token'\nAPI_KEY_HEADER = 'X-Api-Key-Header'\nSECRET_PATH = '/run/secrets/app_secret'\n"}),
    ("valid dataclass", {"m.py": "from dataclasses import dataclass\n\n\n@dataclass\nclass P:\n    a: int\n\n    def g(self):\n        return self.a\n"}),
    ("valid *args / **kwargs call", {"m.py": "def f(*args, **kw):\n    return args, kw\n\n\nf(1, 2, 3, a=1)\n"}),
    ("valid try/except import fallback", {"m.py": "try:\n    import json\nexcept ImportError:\n    json = None\n\nprint(json)\n"}),
    ("valid React component with hooks", {"package.json": PKG, "src/Header.jsx": HEADER, "src/logo.svg": "<svg/>", "src/a.css": "a{}",
        "src/App.jsx": "import { useEffect, useState } from 'react'\nimport Header, { Logo } from './Header'\nimport logo from './logo.svg'\nimport './a.css'\n\nexport default function App({ items = [] }) {\n  const [step, setStep] = useState(0)\n  useEffect(() => { const t = setTimeout(() => setStep(1), 10); return () => clearTimeout(t) }, [])\n  return <div><Header title={`Step ${step}`} /><Logo />{items.map((n) => <li key={n}>{n}</li>)}<img src={logo} /> Save & close</div>\n}\n"}),
]


def run_cases() -> dict:
    t0 = time.time()
    rows = []
    for c in CASES:
        with tempfile.TemporaryDirectory() as d:
            for rel, text in c["files"].items():
                p = Path(d) / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
            res = review_project(Path(d))
        file, rule, line = c["expect"]
        found = [f for f in res["findings"] if f["file"] == file and f["rule"] == rule]
        rows.append({"name": c["name"], "category": c["category"], "expected": f"{rule} @ {file}:{line}", "found": bool(found), "right_line": any(f["line"] == line for f in found),
                     "got": sorted({f["rule"] for f in res["findings"] if f["severity"] != "low"})})
    clean = []
    for name, files in CLEAN:
        with tempfile.TemporaryDirectory() as d:
            for rel, text in files.items():
                p = Path(d) / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
            res = review_project(Path(d))
        bad = [f for f in res["findings"] if f["severity"] in ("high", "medium")]
        clean.append({"name": name, "false_positives": [f"{f['rule']}@{f['file']}:{f['line']}" for f in bad]})
    cats: dict[str, dict] = {}
    for r in rows:
        c = cats.setdefault(r["category"], {"cases": 0, "found": 0, "right_line": 0})
        c["cases"] += 1; c["found"] += r["found"]; c["right_line"] += r["right_line"]
    n = len(rows)
    return {"cases": n, "found": sum(r["found"] for r in rows), "right_line": sum(r["right_line"] for r in rows), "by_category": cats, "rows": rows, "clean_cases": clean,
            "clean_false_positives": sum(len(c["false_positives"]) for c in clean), "seconds": round(time.time() - t0, 2)}


def run_corpus(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        root = Path(p)
        if not root.is_dir():
            continue
        t0 = time.time()
        r = review_project(root)
        sev = r["summary"]["by_severity"]
        out.append({"path": str(p), "files": r["coverage"]["files_analysed"], "ms": int((time.time() - t0) * 1000), "high": sev.get("high", 0), "medium": sev.get("medium", 0), "low": sev.get("low", 0),
                    "high_medium_findings": [f"{f['file']}:{f['line']} {f['rule']}" for f in r["findings"] if f["severity"] in ("high", "medium")][:20]})
    return out


def to_markdown(res: dict, corpus: list[dict]) -> str:
    L = ["# Strict review benchmark", "", f"{res['cases']} seeded mistakes: **{res['found']} found** ({res['found'] / res['cases']:.0%}), **{res['right_line']} on exactly the right line** ({res['right_line'] / res['cases']:.0%}). "
         f"{len(res['clean_cases'])} clean programs: **{res['clean_false_positives']} false alarms** at high/medium severity. Took {res['seconds']} s.", "",
         "| Category | Seeded mistakes | Found | Right line |", "|---|---|---|---|"]
    for k, v in res["by_category"].items():
        L.append(f"| {k} | {v['cases']} | {v['found']} | {v['right_line']} |")
    if corpus:
        L += ["", "## Clean-code check on real code (high/medium findings should be zero for working code)", "", "| Folder | Files | Time | High | Medium | Low |", "|---|---|---|---|---|---|"]
        for c in corpus:
            L.append(f"| `{c['path']}` | {c['files']} | {c['ms']} ms | {c['high']} | {c['medium']} | {c['low']} |")
    missed = [r for r in res["rows"] if not r["found"]]
    if missed:
        L += ["", "## Missed", ""] + [f"- {r['name']} (expected {r['expected']})" for r in missed]
    L += ["", "## Every case", "", "| Case | Expected | Found | Right line |", "|---|---|---|---|"]
    for r in res["rows"]:
        L.append(f"| {r['name']} | `{r['expected']}` | {'yes' if r['found'] else 'NO'} | {'yes' if r['right_line'] else 'NO'} |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.review.bench")
    ap.add_argument("--corpus", nargs="*", default=[], help="folders of working code to check for false alarms")
    ap.add_argument("--out", default="", help="write the Markdown report here")
    a = ap.parse_args(argv)
    res = run_cases()
    corpus = run_corpus(a.corpus)
    md = to_markdown(res, corpus)
    print(md)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        Path(a.out).with_suffix(".json").write_text(json.dumps({"results": res, "corpus": corpus}, indent=2), encoding="utf-8")
    return 0 if res["found"] == res["cases"] and res["clean_false_positives"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
