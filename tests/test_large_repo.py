"""Regression for v1 feedback: on a repo with big docs, the real handler must outrank docs / unrelated code."""
import pytest
from app.agent.tools import RepoTools
from app.ingest import build_index


@pytest.fixture
def big_repo(tmp_path):
    def w(rel, text):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    w("docs/FEATURE_LOG.md", "\n".join(
        f"Phase {i}: delivery creation was reworked; delivery records handled by the delivery service, "
        f"each delivery created with a delivery id." for i in range(400)))
    w("README.md", "# Delivery platform\nDeliveries are created and handled here.\n" * 30)
    w("backend/app/routes/deliveries.py", '''from fastapi import APIRouter

router = APIRouter(prefix="/deliveries")


@router.post("/")
def create_delivery(payload: dict):
    """Create a delivery."""
    return save(payload)


@router.get("/{delivery_id}")
def get_delivery(delivery_id: str):
    return load(delivery_id)
''')
    w("backend/app/services/refund.py", '''def refund_order_for_delivery(db, delivery_id):
    """Refund an order when its delivery was cancelled. Delivery refunds are idempotent."""
    return db.query(delivery_id)
''')
    w("backend/app/models/delivery.py", "class DeliveryPriority:\n    HIGH = 1\n    LOW = 2\n")
    w("frontend/src/App.jsx", "function RootRouter() {\n  // delivery tracking page\n  return null\n}\n")
    w("backend/tests/test_deliveries.py", "def test_create_delivery():\n    assert True  # delivery creation\n")
    w("backend/app/routes/bulk_import.py", '''"""Bulk delivery import from a CSV."""
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
router = APIRouter(prefix="/deliveries", tags=["bulk-import"])


class BulkImportRequest(BaseModel):
    rows: list


@router.post("/bulk-import")
def bulk_import_deliveries(body: BulkImportRequest):
    return [process(r) for r in body.rows]
''')
    w("frontend/src/services/api.js", "export async function bulkImportDeliveries(token, rows) {\n  const r = await fetch(`${API}/deliveries/bulk-import`, {method: \"POST\"});\n  return r.json();\n}\n")
    w("backend/requirements.txt", "fastapi\n")
    return tmp_path


@pytest.mark.parametrize("q", ["where is delivery creation handled",
                               "How does the backend create a delivery? Walk me through the request flow.",
                               "Why am I getting a 500 error when creating a delivery?"])
def test_handler_beats_docs(big_repo, q):
    tools = RepoTools(big_repo, build_index(big_repo))
    top = tools.search_code(q, k=3)
    assert top[0]["file"] == "backend/app/routes/deliveries.py", [(h["file"], h["score"]) for h in top]
    assert top[0]["route"] == "POST /deliveries/"


def test_docs_still_found_when_asked(big_repo):
    tools = RepoTools(big_repo, build_index(big_repo))
    assert tools.search_code("what does the readme say about deliveries", k=2)[0]["file"] in ("README.md", "docs/FEATURE_LOG.md")


def test_zip_upload(tmp_path, monkeypatch):
    import io, zipfile
    from fastapi.testclient import TestClient
    from tests.conftest import FIXTURE
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    import app.main as m
    m._service = None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in FIXTURE.rglob("*.py"):
            z.write(p, "proj/" + p.relative_to(FIXTURE).as_posix())
    r = TestClient(m.app).post("/repositories/upload", files={"file": ("p.zip", buf.getvalue())}, data={"name": "proj"})
    assert r.status_code == 200, r.text
    assert r.json()["files"] >= 4


def test_backend_handler_beats_frontend_client(big_repo):
    top = RepoTools(big_repo, build_index(big_repo)).search_code("POST endpoint for bulk import of deliveries", k=3)
    assert top[0]["route"] == "POST /deliveries/bulk-import", [(h["file"], h["qualname"]) for h in top]


def test_ui_is_served(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app.main as m
    r = TestClient(m.app).get("/")
    assert r.status_code == 200 and "Codebase" in r.text
