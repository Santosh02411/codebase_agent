from app import ingest


def test_copy_local_into_itself_terminates(tmp_path):
    src = tmp_path / "proj"
    (src / "venv" / "lib").mkdir(parents=True)
    (src / "venv" / "lib" / "junk.py").write_text("x = 1")
    (src / "app.py").write_text("print('hi')")
    dest = src / "data" / "repos" / "proj-abc123"  # destination inside the source
    ingest.copy_local(src, dest)
    assert (dest / "app.py").exists()
    assert not (dest / "venv").exists()
    assert not (dest / "data").exists()
