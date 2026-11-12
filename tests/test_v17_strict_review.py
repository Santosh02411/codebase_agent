"""The strict review must find real mistakes: typos, extra braces, missing colons, wrong imports, wrong call arguments. Each case is a mistake someone makes by hand."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.review.engine import review_project
from app.review.pycheck import Project, check_python


def rules(findings):
    return {(f.rule if hasattr(f, "rule") else f["rule"]) for f in findings}


def py(src, files=None):
    files = dict(files or {}); files["m.py"] = src
    return check_python("m.py", src, Project(files))


@pytest.mark.parametrize("src,rule,line", [
    ("def f(x)\n    return x\n", "PY-SYNTAX", 1),                                  # missing colon
    ("def f(x):\n    return (x + 1\n", "PY-SYNTAX", 2),                           # unclosed parenthesis
    ("def f(x):\n    return x)\n", "PY-SYNTAX", 2),                               # extra parenthesis
    ("def f(x):\n    retrun x\n", "PY-SYNTAX", 2),                                # misspelled keyword
    ("def f(x):\n  y = 1\n    return y\n", "PY-SYNTAX", 3),                       # indentation
    ("s = 'abc\n", "PY-SYNTAX", 1),                                               # unterminated string
    ("def total(items):\n    return summ\n", "PY-UNDEFINED", 2),                 # undefined name
    ("def total(items):\n    s = 0\n    for i in itmes:\n        s += i\n    return s\n", "PY-UNDEFINED", 3),   # misspelled variable
    ("import os\nx = os.pth.join('a')\n", "PY-MODATTR", 2),                       # misspelled stdlib attribute
    ("def f():\n    return 1 / 0\n", "PY-DIVZERO", 2),
    ("def f(items):\n    assert (items, 'empty')\n", "PY-ASSERT", 2),
    ("x = 'a' + 1\n", "PY-TYPEMIX", 1),
    ("def f(a, b):\n    return a\nf(1)\n", "PY-ARITY", 3),                         # missing argument
    ("def f(a, b):\n    return a\nf(1, 2, 3)\n", "PY-ARITY", 3),                   # too many
    ("def f(speed):\n    return speed\nf(spped=3)\n", "PY-ARITY", 3),              # misspelled keyword
    ("class A:\n    def __init__(self):\n        self.name = 1\n    def g(self):\n        return self.nmae\n", "PY-ATTR", 5),
    ("class A:\n    def g():\n        return 1\n", "PY-NOSELF", 2),
    ("def f(x=[]):\n    return x\n", "PY-MUTDEF", 1),
    ("def a():\n    return 1\ndef a():\n    return 2\n", "PY-REDEF", 3),
    ("def f():\n    return 1\n    print('never')\n", "PY-UNREACHABLE", 3),
    ("import subprocess\nsubprocess.run('ls', shell=True)\n", "PY-SHELL", 2),
    ("def q(c, n):\n    c.execute(\"SELECT * FROM t WHERE n = '\" + n + \"'\")\n", "PY-SQLI", 2),
    ("d = {'a': 1, 'a': 2}\n", "PY-DUPKEY", 1),
    ("x = 'a %s %s' % (1,)\n", "PY-FORMAT", 1),
])
def test_python_mistakes_are_found_on_the_right_line(src, rule, line):
    hits = [f for f in py(src) if f.rule == rule]
    assert hits, f"{rule} not reported; got {rules(py(src))}"
    assert hits[0].line == line


def test_did_you_mean_suggestions_point_at_the_real_name():
    assert "`items`" in next(f.message for f in py("def f(items):\n    return itmes\n") if f.rule == "PY-UNDEFINED")
    assert "`path`" in next(f.message for f in py("import os\nos.pth\n") if f.rule == "PY-MODATTR")


def test_imports_between_project_files_are_checked():
    files = {"services/eta.py": "def calculate_eta(a):\n    return a\n", "services/__init__.py": ""}
    f1 = py("from services.eta import calculate_etaa\n", files)
    assert any(f.rule == "PY-IMPORT" and "calculate_eta" in f.message for f in f1)
    f2 = py("from services.etaa import x\n", files)
    assert any(f.rule == "PY-IMPORT" and "services.eta" in f.message for f in f2)
    f3 = py("from services.eta import calculate_eta\ncalculate_eta(1, 2)\n", files)
    assert any(f.rule == "PY-ARITY" for f in f3)


@pytest.mark.parametrize("src", [
    "import os\nfrom typing import List\n\n\ndef f(items: 'List[int]') -> int:\n    return len(items) + len(os.sep)\n",
    "class A:\n    x = 1\n    def g(self):\n        return self.x\n",
    "def f(*args, **kw):\n    return args, kw\nf(1, 2, 3, a=1)\n",
    "from dataclasses import dataclass\n\n@dataclass\nclass P:\n    a: int\n    def g(self):\n        return self.a\n",
    "try:\n    import json\nexcept ImportError:\n    json = None\n\nprint(json)\n",
    "def outer():\n    n = 0\n    def inc():\n        nonlocal n\n        n += 1\n    inc()\n    return n\n",
    "squares = [x * x for x in range(3)]\nprint(squares)\n",
    "from __future__ import annotations\n\n\ndef f(x: Later) -> None:\n    return None\n\n\nclass Later:\n    pass\n",
    "from lib import Base\n\n\nclass B(Base):\n    def g(self):\n        return self.anything\n",     # unknown base: attributes cannot be judged
])
def test_valid_code_produces_no_errors(src):
    bad = [f for f in py(src) if f.severity == "high"]
    assert not bad, [(f.rule, f.message) for f in bad]


def test_js_syntax_and_typos(tmp_path):
    (tmp_path / "a.js").write_text("function total(items) {\n  let sum = 0;\n  if (sum = 0) {\n    return 0;\n  }\n  return summ;\n}\n}\n")
    r = review_project(tmp_path)
    got = {f["rule"] for f in r["findings"]}
    assert {"JS-SYNTAX", "JS-ASSIGNCOND", "JS-UNDEFINED"} <= got
    (tmp_path / "b.js").write_text("function f() {\n  return 1;\n")                 # missing closing brace
    assert any(f["rule"] == "JS-SYNTAX" and f["file"] == "b.js" for f in review_project(tmp_path)["findings"])


def test_json_html_and_whole_project_report(tmp_path):
    (tmp_path / "d.json").write_text('{"a": 1,}')
    (tmp_path / "i.html").write_text("<div><span>x</div>")
    (tmp_path / "ok.py").write_text("def f():\n    return 1\n")
    r = review_project(tmp_path)
    assert {f["file"] for f in r["findings"]} == {"d.json", "i.html"}
    langs = {l["language"]: l for l in r["coverage"]["languages"]}
    assert langs["python"]["files"] == 1 and "undefined names" in langs["python"]["depth"]
    assert r["limits"] and r["duration_ms"] < 5000


def test_every_file_is_reviewed_not_a_sample(tmp_path):
    for i in range(60):
        (tmp_path / f"m{i}.py").write_text("def f():\n    return 1\n" if i != 59 else "def f()\n    return 1\n")
    r = review_project(tmp_path)
    assert r["coverage"]["files_analysed"] == 60 and [f["file"] for f in r["findings"]] == ["m59.py"]


# ---- API + sync from the original folder --------------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    import app.main as m
    m._service = None
    src = tmp_path / "proj"; src.mkdir()
    (src / "a.py").write_text("def f(x):\n    return x\n")
    c = TestClient(m.app)
    rid = c.post("/repositories", json={"source": str(src), "name": "p"}).json()["id"]
    return c, rid, src


def test_edits_in_the_original_folder_are_only_seen_after_sync(client):
    c, rid, src = client
    assert c.post(f"/repositories/{rid}/review/static", json={}).json()["summary"]["total"] == 0
    (src / "a.py").write_text("def f(x)\n    return x\n")            # the user introduces an error in THEIR folder
    (src / "b.py").write_text("print(undefined_name)\n")
    st = c.get(f"/repositories/{rid}/source-status").json()
    assert st["count"] == 2 and {x["file"] for x in st["changed"]} == {"a.py", "b.py"}
    assert c.post(f"/repositories/{rid}/review/static", json={}).json()["summary"]["total"] == 0     # the server still has the old copy
    assert c.post(f"/repositories/{rid}/refresh").status_code == 200
    assert c.get(f"/repositories/{rid}/source-status").json()["count"] == 0
    rules = {f["rule"] for f in c.post(f"/repositories/{rid}/review/static", json={}).json()["findings"]}
    assert {"PY-SYNTAX", "PY-UNDEFINED"} <= rules


def test_agent_review_mode_includes_the_strict_findings_for_every_file(client):
    c, rid, src = client
    (src / "zz.py").write_text("def g():\n    return nothere\n")
    c.post(f"/repositories/{rid}/refresh")
    r = c.post("/review", json={"repo_id": rid}).json()
    assert any("PY-UNDEFINED" in f["message"] and f["file"] == "zz.py" for f in r["findings"])


def test_execution_flow_follows_real_calls_in_source_order():
    from app.ingest import build_index
    from app.intel import system_graph as sgm
    idx = build_index(Path(__file__).parent / "fixtures" / "delivery_sync")
    f = sgm.flow(idx.graph, "delivery_app.py::create_delivery")
    assert [(s["to"], s["resolved"]) for s in f["steps"] if s["depth"] == 1][:2] == [("validate_payload", True), ("calculate_delivery_eta", True)]
    assert f["participants"][0]["file"] == "delivery_app.py" and sgm.flow(idx.graph, "nope") is None


# ---- React / JavaScript projects -------------------------------------------------------------------------------------------------------
def _react(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return review_project(tmp_path)


PKG = '{"name":"app","dependencies":{"react":"^19","react-dom":"^19"}}'
HEADER = "export default function Header({ title }) {\n  return <h1>{title}</h1>\n}\nexport const Logo = () => <i />\n"


@pytest.mark.parametrize("name,body,rule,must", [
    ("bad import path", "import Header from './Hedaer'\nexport default function A() { return <Header /> }\n", "JS-IMPORT", "Header"),
    ("missing named export", "import Header, { Banner } from './Header'\nexport default function A() { return <Header><Banner /></Header> }\n", "JS-EXPORT", "Banner"),
    ("typo in package name", "import React from 'reactt'\nexport default function A() { return <div /> }\n", "JS-PACKAGE", "react"),
    ("misspelled component", "import Header from './Header'\nexport default function A() { return <Hedaer title='x' /> }\n", "JS-UNDEFINED", "Header"),
    ("hook not imported", "export default function A() { const [a, b] = useState(0); return <div>{a}{b}</div> }\n", "JS-UNDEFINED", "useState"),
    ("misspelled variable", "import { useState } from 'react'\nexport default function A() { const [name, setName] = useState(''); return <input value={nmae} onChange={() => setName('')} /> }\n", "JS-UNDEFINED", "name"),
    ("unclosed JSX expression", "export default function A() { return <button onClick={() => { go() }>Go</button> }\n", "JS-SYNTAX", ""),
    ("extra closing brace", "export default function A() {\n  return 1\n}\n}\n", "JS-SYNTAX", ""),
    ("missing closing brace", "export default function A() {\n  return 1\n", "JS-SYNTAX", ""),
])
def test_react_mistakes_are_found(tmp_path, name, body, rule, must):
    r = _react(tmp_path, {"package.json": PKG, "src/Header.jsx": HEADER, "src/A.jsx": body})
    hits = [f for f in r["findings"] if f["file"] == "src/A.jsx" and f["rule"] == rule]
    assert hits, f"{name}: got {[(f['rule'], f['message'][:60]) for f in r['findings']]}"
    assert must in hits[0]["message"]


def test_valid_react_code_has_no_errors(tmp_path):
    ok = ("import { useEffect, useState } from 'react'\nimport Header, { Logo } from './Header'\nimport logo from './logo.svg'\nimport './a.css'\n\n"
          "export default function App({ items = [] }) {\n  const [step, setStep] = useState(0)\n  const { a, b = 2, ...rest } = { a: 1 }\n"
          "  useEffect(() => { const t = setTimeout(() => setStep(1), 10); return () => clearTimeout(t) }, [])\n"
          "  async function load() { try { return await (await fetch('/x')).json() } catch (e) { console.error(e) } }\n"
          "  return <div><Header title={`Step ${step}`} /><Logo />{items.map((n) => <li key={n}>{n}</li>)}{a}{b}{rest.x}<img src={logo} /> Save & close</div>\n}\n")
    r = _react(tmp_path, {"package.json": PKG, "src/Header.jsx": HEADER, "src/logo.svg": "<svg/>", "src/a.css": "a{}", "src/App.jsx": ok})
    assert [f for f in r["findings"] if f["severity"] in ("high", "medium")] == []


def test_every_deliberate_error_in_a_small_react_app_is_reported_together(tmp_path):
    files = {"package.json": PKG, "src/Header.jsx": HEADER,
             "src/Step.jsx": ("import { useState } from 'react'\nimport Header, { Banner } from './Header'\nimport Footer from './Footr'\n\n"
                              "export default function Step() {\n  const [name, setName] = useSate('')\n  return (\n    <div>\n      <Hedaer />\n      <input value={nmae} onChange={() => setName('')} />\n    </div>\n  )\n}\n")}
    r = _react(tmp_path, files)
    got = {(f["rule"], f["line"]) for f in r["findings"] if f["file"] == "src/Step.jsx" and f["severity"] == "high"}
    assert {("JS-EXPORT", 2), ("JS-IMPORT", 3), ("JS-UNDEFINED", 6), ("JS-UNDEFINED", 9), ("JS-UNDEFINED", 10)} <= got


def test_file_listing_shows_the_whole_folder_not_just_indexed_code(client):
    c, rid, src = client
    (src / "public").mkdir(); (src / "public" / "logo.png").write_bytes(b"\x89PNG....")
    (src / "README.md").write_text("# hi\n")
    (src / "node_modules").mkdir(); (src / "node_modules" / "x.js").write_text("1")
    c.post(f"/repositories/{rid}/refresh")
    r = c.get(f"/repositories/{rid}/files").json()
    paths = {f["path"]: f for f in r["files"]}
    assert {"a.py", "README.md", "public/logo.png"} <= set(paths) and "node_modules/x.js" not in paths
    assert paths["a.py"]["indexed"] is True and paths["public/logo.png"]["indexed"] is False
    assert isinstance(r["skipped_dirs"], list)          # dependency folders are never copied into the working copy in the first place


def test_flow_includes_react_components_a_function_renders(tmp_path):
    from app.ingest import build_index
    from app.intel import system_graph as sgm
    (tmp_path / "Header.jsx").write_text("export default function Header() {\n  return <h1>hi</h1>\n}\n")
    (tmp_path / "App.jsx").write_text("import Header from './Header'\n\nexport default function App() {\n  return <div><Header /></div>\n}\n")
    idx = build_index(tmp_path)
    f = sgm.flow(idx.graph, "App.jsx::App", root=tmp_path)
    assert [(s["label"], s["kind"], s["resolved"]) for s in f["steps"]] == [("<Header />", "render", True)]
