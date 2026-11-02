import pytest

from app.ingest import build_index
from app.intel.ts_core import available_grammars
from app.retrieval.embeddings import HashingEmbedder
from tests.helpers_poly import write_poly

pytestmark = pytest.mark.skipif(not all(available_grammars().values()), reason="tree-sitter grammars not installed")


@pytest.fixture(scope="module")
def idx(tmp_path_factory):
    d = tmp_path_factory.mktemp("poly")
    write_poly(d)
    return build_index(d, HashingEmbedder())


def edges(g):
    return {(s, t): c for s, m in g.call_edges.items() for t, c in m.items()}


def test_module_graph_resolves_each_language(idx):
    g = idx.graph
    mod = {(e.src, e.dst) for e in g.module_edges}
    assert ("py/app/main.py", "py/app/services/eta.py") in mod        # from .services.eta import ...
    assert ("py/app/main.py", "py/app/util.py") in mod                # from . import util / import app.util as u2
    assert ("py/tests/test_main.py", "py/app/main.py") in mod         # absolute import resolved across a source root
    assert ("web/src/api.ts", "web/src/ui.ts") in mod and ("web/src/api.ts", "web/src/lib/index.ts") in mod
    assert ("java/src/com/x/A.java", "java/src/com/y/B.java") in mod
    assert ("go/main.go", "go/internal/db/db.go") in mod              # go.mod lives in a sub-folder
    assert ("rs/src/main.rs", "rs/src/util.rs") in mod and ("rs/src/main.rs", "rs/src/models.rs") in mod
    assert ("c/main.c", "c/util.h") in mod
    assert g.external["web/src/api.ts"] == {"axios"} and g.external["c/main.c"] == {"stdio.h"}
    assert g.external["go/main.go"] == {"github.com/gin-gonic/gin"}


def test_call_graph_resolution_and_confidence(idx):
    e = edges(idx.graph)
    m = "py/app/main.py::"
    assert e[(m + "handler", "py/app/services/eta.py::calculate")] == "import"      # eta.calculate via module alias
    assert e[(m + "Child.helper", "py/app/services/eta.py::calculate")] == "import"  # from-import
    assert e[(m + "handler", "py/app/util.py::fmt")] == "import"
    assert e[(m + "handler", m + "local")] == "local"
    assert e[(m + "Child.run", m + "Child.helper")] == "self"
    assert e[("py/tests/test_main.py::test_it", m + "handler")] == "import"
    assert e[("web/src/api.ts::Svc.go", "web/src/api.ts::Svc.stop")] == "self"
    assert e[("web/src/api.ts::load", "web/src/ui.ts::render")] == "import"          # import { render as r }; r()
    assert e[("web/src/api.ts::load", "web/src/ui.ts::draw")] == "import"            # import * as ui; ui.draw()
    assert e[("web/src/api.ts::load", "web/src/lib/index.ts::def")] == "import"      # default import
    jb = "java/src/com/y/B.java::"
    assert e[("java/src/com/x/A.java::A.a", jb + "B.b")] == "self"                   # inherited method, implicit this
    assert e[("java/src/com/x/A.java::A.a", jb + "B.stat")] == "import"
    assert e[("go/main.go::main", "go/internal/db/db.go::Open")] == "import"
    assert e[("rs/src/main.rs::main", "rs/src/util.rs::go")] == "import"
    assert e[("rs/src/main.rs::main", "rs/src/models.rs::User.new")] == "import"
    assert e[("c/main.c::main", "c/util.c::add")] == "unique"


def test_no_false_edges_for_builtins_and_common_names(idx):
    e = edges(idx.graph)
    assert not any(t.endswith("::str") for _, t in e)
    # `Child().run()` / `super().run()` have an unknown receiver and "run" is too common to guess
    assert (("py/app/main.py::handler", "py/app/services/eta.py::Base.run")) not in e


def test_inheritance_and_callers(idx):
    g = idx.graph
    assert g.base_ids["py/app/main.py::Child"] == ["py/app/services/eta.py::Base"]
    assert g.derived["py/app/services/eta.py::Base"] == ["py/app/main.py::Child"]
    assert g.base_ids["java/src/com/x/A.java::A"] == ["java/src/com/y/B.java::B"]
    callers = {s.qualname for s, _ in g.callers("py/app/main.py::handler")}
    assert callers == {"test_it"}
    assert g.call_resolved / g.call_total > 0.7


def test_impact_analysis_and_subgraphs(idx):
    g = idx.graph
    imp = g.impact("py/app/util.py")
    assert [d["file"] for d in imp["dependents"]][:2] == ["py/app/main.py", "py/tests/test_main.py"]
    assert imp["tests"] == ["py/tests/test_main.py"]
    sub = g.call_subgraph("py/app/main.py::handler", depth=2, direction="both")
    ids = {n["id"] for n in sub["nodes"]}
    assert {"py/app/main.py::handler", "py/app/util.py::fmt", "py/tests/test_main.py::test_it"} <= ids
    levels = {n["id"]: n["level"] for n in sub["nodes"]}
    assert levels["py/tests/test_main.py::test_it"] < 0 < levels["py/app/util.py::fmt"]     # callers left, callees right
    ms = g.module_subgraph("py/app/main.py", depth=1)
    assert {"py/app/util.py", "py/tests/test_main.py"} <= {n["id"] for n in ms["nodes"]}
    ov = g.modules_overview()
    assert not ov["collapsed"] and len(ov["nodes"]) >= 15


def test_overview_collapses_large_repos(tmp_path):
    for i in range(30):
        d = tmp_path / f"pkg{i % 5}"
        d.mkdir(exist_ok=True)
        (d / f"m{i}.py").write_text("x = 1\n")
    g = build_index(tmp_path, HashingEmbedder()).graph
    assert g.modules_overview(limit=10)["collapsed"]


def test_stats(idx):
    from app.intel.stats import repo_stats
    st = repo_stats(idx)
    langs = {l["language"]: l for l in st["languages"]}
    assert {"python", "typescript", "java", "go", "rust", "c"} <= set(langs)
    assert st["symbols"]["classes"] >= 4 and st["symbols"]["functions"] >= 10 and st["symbols"]["methods"] >= 5
    assert st["tests"]["files"] == 1 and st["tests"]["cases"] == 1
    assert "github.com/gin-gonic/gin" in {d["name"] for d in st["dependencies"]["declared"]}
    assert {"axios", "stdio.h"} <= {d["name"] for d in st["dependencies"]["external_imports"]}
    assert st["graph"]["call_edges"] >= 15 and st["graph"]["call_resolution_pct"] > 70
    assert st["parsers"]["python-ast"] >= 5 and st["parsers"]["tree-sitter:rust"] == 3
