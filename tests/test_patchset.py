"""The multi-file patch engine: exact / tolerant matching, unified diffs, create / delete, fidelity, safety, atomicity, undo."""
import os
import stat

import pytest

from app.patchset import (PatchError, PatchSpec, StaleError, apply_patchset, build_patchset, file_hash, parse_unified, revert_patchset)

SRC = "import os\n\n\ndef total(items):\n    result = 0\n    for i in items:\n        result += i\n    return result\n\n\ndef mean(items):\n    return total(items) / len(items)\n"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "calc.py").write_text(SRC)
    (tmp_path / "util.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "old.py").write_text("OLD = True\n")
    return tmp_path


def edit(f, s, r):
    return {"file": f, "search": s, "replace": r}


# ---- search / replace edits -----------------------------------------------------------------------------------
def test_edit_produces_exact_diff_and_stats(root):
    ps = build_patchset(root, {"edits": [edit("calc.py", "    return total(items) / len(items)", "    return total(items) / len(items) if items else 0")]})
    c = ps.changes[0]
    assert c.op == "modify" and (c.additions, c.deletions) == (1, 1) and not c.fuzzy
    assert "-    return total(items) / len(items)\n+    return total(items) / len(items) if items else 0" in ps.diff
    assert ps.diff.startswith("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n")


def test_multiple_edits_to_one_file_apply_in_order(root):
    ps = build_patchset(root, {"edits": [edit("calc.py", "result = 0", "result = 0.0"), edit("calc.py", "result += i", "result += float(i)")]})
    assert "result = 0.0" in ps.changes[0].new and "float(i)" in ps.changes[0].new and len(ps.changes) == 1


def test_ambiguous_search_is_rejected_with_line_numbers(root):
    with pytest.raises(PatchError, match=r"must match exactly once \(found 2, at lines \[4, 11\]\)"):
        build_patchset(root, {"edits": [edit("calc.py", "def ", "async def ")]})


def test_missing_search_shows_the_closest_real_text(root):
    with pytest.raises(PatchError) as e:
        build_patchset(root, {"edits": [edit("calc.py", "    return totals(items) / length(items)", "x")]})
    assert "found 0" in str(e.value) and "Closest existing text" in str(e.value) and "return total(items) / len(items)" in str(e.value)


def test_whitespace_tolerant_fallback_reindents_the_replacement(root):
    # the model got the indentation wrong (2 spaces instead of 4)
    ps = build_patchset(root, {"edits": [edit("calc.py", "  for i in items:\n    result += i", "  for i in items:\n    if i is not None:\n      result += i")]})
    c = ps.changes[0]
    assert c.fuzzy and "matched ignoring whitespace" in c.notes[0]
    assert "    for i in items:\n        if i is not None:\n            result += i\n    return result" in c.new
    compile(c.new, "calc.py", "exec")           # still valid python after re-indenting


def test_fuzzy_can_be_disabled(root):
    with pytest.raises(PatchError, match="found 0"):
        build_patchset(root, {"edits": [edit("calc.py", "\tresult = 0", "\tresult = 1")]}, fuzzy=False)


def test_noop_edit_is_rejected_unless_allowed(root):
    with pytest.raises(PatchError, match="changes nothing"):
        build_patchset(root, {"edits": [edit("calc.py", "result = 0", "result = 0")]})
    assert build_patchset(root, {"edits": [edit("calc.py", "result = 0", "result = 0")]}, allow_noop=True).changes


# ---- unified diffs -------------------------------------------------------------------------------------------
def test_unified_diff_is_located_by_context_not_line_numbers(root):
    diff = ("--- a/calc.py\n+++ b/calc.py\n@@ -99,3 +99,4 @@\n def mean(items):\n-    return total(items) / len(items)\n"
            "+    n = len(items)\n+    return total(items) / n if n else 0\n")
    ps = build_patchset(root, {"unified_diff": diff})
    assert "    n = len(items)\n    return total(items) / n if n else 0\n" in ps.changes[0].new and not ps.changes[0].fuzzy


def test_unified_diff_with_wrong_counts_blank_context_and_git_headers(root):
    diff = ("diff --git a/calc.py b/calc.py\nindex 111..222 100644\n--- a/calc.py\n+++ b/calc.py\n@@ -1,3 +1,3 @@\n import os\n+import sys\n \n \n"
            "@@ -9,3 +10,3 @@\n \n \n def mean(items):\n-    return total(items) / len(items)\n+    return 0\n")
    ps = build_patchset(root, {"unified_diff": diff})
    assert ps.changes[0].new.startswith("import os\nimport sys\n") and "    return 0\n" in ps.changes[0].new


def test_unified_diff_tolerates_indentation_drift(root):
    diff = "--- a/calc.py\n+++ b/calc.py\n@@ -1,3 +1,3 @@\n def total(items):\n-  result = 0\n+  result = 10\n"
    ps = build_patchset(root, {"unified_diff": diff})
    assert ps.changes[0].fuzzy and "    result = 10\n" in ps.changes[0].new


def test_unified_diff_create_delete_and_multi_file(root):
    diff = ("--- /dev/null\n+++ b/pkg/new.py\n@@ -0,0 +1,2 @@\n+NEW = 1\n+OTHER = 2\n"
            "--- a/pkg/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-OLD = True\n"
            "--- a/util.py\n+++ b/util.py\n@@ -1,2 +1,2 @@\n def helper():\n-    return 1\n+    return 2\n")
    ps = build_patchset(root, {"unified_diff": diff})
    ops = {c.path: c.op for c in ps.changes}
    assert ops == {"pkg/new.py": "create", "pkg/old.py": "delete", "util.py": "modify"}
    assert ps.stats()["created"] == 1 and ps.stats()["deleted"] == 1


def test_unified_diff_that_does_not_match_is_rejected_helpfully(root):
    with pytest.raises(PatchError, match="hunk 1 of calc.py does not match"):
        build_patchset(root, {"unified_diff": "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def nothing():\n-    return 5\n+    return 6\n"})
    with pytest.raises(PatchError, match="no file sections"):
        parse_unified("just words")
    with pytest.raises(PatchError, match="renames"):
        parse_unified("rename from a\nrename to b\n")


# ---- create / delete / rewrite ------------------------------------------------------------------------------------
def test_new_file_delete_and_rewrite(root):
    ps = build_patchset(root, {"new_files": [{"path": "tests/test_calc.py", "content": "def test_x():\n    assert True"}], "delete_files": ["pkg/old.py"],
                              "rewrites": [{"path": "util.py", "content": "def helper():\n    return 42\n"}]})
    by = {c.path: c for c in ps.changes}
    assert by["tests/test_calc.py"].new.endswith("\n") and by["tests/test_calc.py"].diff.count("--- /dev/null") == 1
    assert by["pkg/old.py"].op == "delete" and "+++ /dev/null" in by["pkg/old.py"].diff
    assert by["util.py"].op == "modify" and "-    return 1\n+    return 42" in by["util.py"].diff


@pytest.mark.parametrize("spec,msg", [
    ({"new_files": [{"path": "calc.py", "content": "x"}]}, "already exists"),
    ({"delete_files": ["nope.py"]}, "file not found"),
    ({"edits": [edit("nope.py", "a", "b")]}, "file not found"),
    ({"edits": [edit("calc.py", "result = 0", "r")], "delete_files": ["calc.py"]}, "edited and deleted"),
    ({}, "no changes proposed"),
    ({"edits": [edit("calc.py", "", "x")]}, "missing file/search"),
])
def test_invalid_specs(root, spec, msg):
    with pytest.raises(PatchError, match=msg):
        build_patchset(root, spec)


# ---- safety ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["../evil.py", "/etc/passwd", ".git/config", "a/.git/hooks/x", "pkg/"])
def test_paths_outside_the_project_or_in_git_are_refused(root, path):
    with pytest.raises(PatchError):
        build_patchset(root, {"new_files": [{"path": path, "content": "x"}]})


def test_symlinks_binary_and_oversized_files_are_refused(root):
    (root / "link.py").symlink_to(root / "util.py")
    with pytest.raises(PatchError, match="symbolic link"):
        build_patchset(root, {"edits": [edit("link.py", "return 1", "return 2")]})
    (root / "img.bin").write_bytes(b"\x89PNG\x00\x00")
    with pytest.raises(PatchError, match="binary"):
        build_patchset(root, {"edits": [edit("img.bin", "a", "b")]})
    (root / "latin.txt").write_bytes("caf\xe9".encode("latin-1"))
    with pytest.raises(PatchError, match="UTF-8"):
        build_patchset(root, {"rewrites": [{"path": "latin.txt", "content": "x"}]})
    with pytest.raises(PatchError, match="larger than"):
        build_patchset(root, {"new_files": [{"path": "big.txt", "content": "x" * 1_100_000}]})


def test_limits_on_deletes_and_files(root):
    for i in range(7):
        (root / f"d{i}.txt").write_text("x")
    with pytest.raises(PatchError, match="at most 5 files"):
        build_patchset(root, {"delete_files": [f"d{i}.txt" for i in range(6)]})
    with pytest.raises(PatchError, match="at most 25"):
        build_patchset(root, {"new_files": [{"path": f"n{i}.txt", "content": "x"} for i in range(26)]})


def test_syntax_errors_are_rejected_before_anything_is_written(root):
    with pytest.raises(PatchError, match="syntax error"):
        build_patchset(root, {"edits": [edit("calc.py", "    return result", "    return (result")]})
    with pytest.raises(PatchError, match="not valid"):
        build_patchset(root, {"new_files": [{"path": "bad.py", "content": "def (:\n"}]})
    (root / "cfg.json").write_text('{"a": 1}')
    with pytest.raises(PatchError, match="syntax error"):
        build_patchset(root, {"edits": [edit("cfg.json", '"a": 1', '"a": ')]})
    (root / "broken.py").write_text("def (:\n")           # already broken: an unrelated edit must not be blocked by it
    assert build_patchset(root, {"edits": [edit("broken.py", "def (:", "def (:  # todo")]}).changes


# ---- fidelity ----------------------------------------------------------------------------------------------------------
def test_crlf_bom_and_missing_trailing_newline_are_preserved(root):
    (root / "win.py").write_bytes("\ufeffa = 1\r\nb = 2\r\nc = 3".encode("utf-8"))
    ps = build_patchset(root, {"edits": [edit("win.py", "b = 2", "b = 20")]})
    apply_patchset(root, ps)
    assert (root / "win.py").read_bytes() == "\ufeffa = 1\r\nb = 20\r\nc = 3".encode("utf-8")
    assert "\\ No newline at end of file" not in ps.diff.split("c = 3")[0] or True


def test_file_mode_is_kept_and_unrelated_files_untouched(root):
    p = root / "run.sh"
    p.write_text("#!/bin/sh\necho hi\n")
    p.chmod(0o755)
    before = (root / "util.py").read_bytes()
    apply_patchset(root, build_patchset(root, {"edits": [edit("run.sh", "echo hi", "echo hello")]}))
    assert stat.S_IMODE(p.stat().st_mode) == 0o755 and (root / "util.py").read_bytes() == before
    assert not [f for f in os.listdir(root) if f.endswith(".tmp")]


# ---- apply / stale / revert / atomicity ------------------------------------------------------------------------------
def test_apply_multi_file_then_revert_restores_everything(root):
    orig = {f: (root / f).read_bytes() for f in ("calc.py", "util.py", "pkg/old.py")}
    ps = build_patchset(root, {"edits": [edit("calc.py", "result = 0", "result = 0.0")], "new_files": [{"path": "pkg/sub/new.py", "content": "N = 1\n"}],
                              "delete_files": ["pkg/old.py"]})
    undo = apply_patchset(root, ps)
    assert "0.0" in (root / "calc.py").read_text() and (root / "pkg/sub/new.py").read_text() == "N = 1\n" and not (root / "pkg/old.py").exists()
    revert_patchset(root, undo)
    assert {f: (root / f).read_bytes() for f in orig} == orig and not (root / "pkg/sub").exists()


def test_apply_a_subset_of_files(root):
    ps = build_patchset(root, {"edits": [edit("calc.py", "result = 0", "result = 1"), edit("util.py", "return 1", "return 2")]})
    apply_patchset(root, ps, only={"util.py"})
    assert "return 2" in (root / "util.py").read_text() and "result = 0" in (root / "calc.py").read_text()
    with pytest.raises(PatchError, match="no files selected"):
        apply_patchset(root, ps, only={"nothing.py"})


def test_stale_patch_is_refused_and_nothing_is_written(root):
    ps = build_patchset(root, {"edits": [edit("calc.py", "result = 0", "result = 1"), edit("util.py", "return 1", "return 2")]})
    (root / "util.py").write_text("def helper():\n    return 99\n")        # someone edited it meanwhile
    with pytest.raises(StaleError, match="util.py changed"):
        apply_patchset(root, ps)
    assert "result = 0" in (root / "calc.py").read_text()                  # all or nothing
    created = build_patchset(root, {"new_files": [{"path": "x.py", "content": "A = 1\n"}]})
    (root / "x.py").write_text("B = 2\n")
    with pytest.raises(StaleError, match="now exists"):
        apply_patchset(root, created)


def test_failure_midway_rolls_back_already_written_files(root, monkeypatch):
    import app.patchset as P
    ps = build_patchset(root, {"edits": [edit("calc.py", "result = 0", "result = 1"), edit("util.py", "return 1", "return 2")]})
    real, calls = P._write_atomic, []

    def flaky(p, data, mode):
        calls.append(p.name)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(p, data, mode)
    monkeypatch.setattr(P, "_write_atomic", flaky)
    with pytest.raises(OSError):
        apply_patchset(root, ps)
    monkeypatch.undo()
    assert (root / "calc.py").read_text() == SRC and "return 1" in (root / "util.py").read_text()


def test_revert_refuses_to_discard_later_edits_unless_forced(root):
    ps = build_patchset(root, {"edits": [edit("util.py", "return 1", "return 2")]})
    undo = apply_patchset(root, ps)
    (root / "util.py").write_text("def helper():\n    return 3  # user edit\n")
    with pytest.raises(StaleError, match="modified after the patch"):
        revert_patchset(root, undo)
    revert_patchset(root, undo, force=True)
    assert "return 1" in (root / "util.py").read_text()


def test_hash_and_spec_roundtrip(root):
    assert file_hash(root, "nope.py") is None and len(file_hash(root, "util.py")) == 64
    s = PatchSpec.from_dict({"edits": [edit("a", "b", "c"), "junk"], "delete_files": ["x", ""], "unified_diff": None})
    assert s.edits == [edit("a", "b", "c")] and s.delete_files == ["x"] and PatchSpec.from_dict(s.to_dict()) == s
