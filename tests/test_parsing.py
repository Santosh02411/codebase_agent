from app.parsing.chunker import chunk_file, chunk_python


def test_python_chunks_are_logical_units():
    src = "import os\n\nX = 1\n\ndef a():\n    return b()\n\nclass C:\n    '''doc'''\n    def m(self):\n        return a()\n"
    chunks = {c.qualname: c for c in chunk_python("m.py", src)}
    assert chunks["a"].kind == "function" and chunks["a"].calls == ["b"]
    assert chunks["C.m"].kind == "method" and chunks["C.m"].calls == ["a"]
    assert chunks["C"].kind == "class"
    assert "import os" in chunks["m.py"].text  # module-level code kept


def test_syntax_error_falls_back_to_windows():
    assert chunk_file("bad.py", "def (:\n" * 3)[0].kind == "block"


def test_js_boundaries():
    src = "import x from 'y'\nexport function login() {\n  return 1\n}\nconst logout = async () => {}\n"
    names = [c.name for c in chunk_file("a.js", src)]
    assert "login" in names and "logout" in names
