def test_hybrid_search_finds_function_by_exact_name(tools):
    assert tools.search_code("calculate_delivery_eta", k=3)[0]["qualname"] == "calculate_delivery_eta"


def test_semantic_style_question(tools):
    assert tools.search_code("where is authentication implemented", k=3)[0]["file"] == "auth.py"


def test_call_graph_expansion(tools):
    hit = tools.search_code("create_delivery", k=1)[0]
    assert "calculate_delivery_eta" in [r["qualname"] for r in tools.related(hit["id"])]


def test_dependencies_and_tools(tools):
    d = tools.get_dependencies("delivery_app.py")
    assert "services/eta.py" in d["internal_files"]
    assert "DEFAULT_SPEED_KMH" in tools.read_file("services/eta.py")
    assert tools.find_symbol("validate_payload")


def test_read_file_blocks_path_traversal(tools):
    import pytest
    with pytest.raises(ValueError):
        tools.read_file("../../etc/passwd")
