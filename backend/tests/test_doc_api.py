"""API integration tests for Step 4A PDF document endpoints."""

import io
import json
from pathlib import Path
from unittest.mock import patch

from app.config import get_settings
from app.db import get_session, save_document, save_document_pages, save_repo
from app.models import Document, DocumentPage, Repo
from tests.test_doc_validator_and_parser import create_simple_pdf_bytes


def test_api_repos_list_endpoint(client):
    session = get_session()
    r = Repo(id="r-list-1", url="https://github.com/pallets/flask", status="ready")
    save_repo(session, r)
    session.close()

    resp = client.get("/api/repos")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    matching = [repo for repo in data if repo["id"] == "r-list-1"]
    assert len(matching) == 1
    assert matching[0]["name"] == "pallets/flask"


def test_api_document_upload_and_duplicate(client, tmp_path: Path):
    settings = get_settings()
    pdf_bytes = create_simple_pdf_bytes(["Test document content on page one."])

    # 1. First upload
    files = [("files", ("guide.pdf", pdf_bytes, "application/pdf"))]
    with patch("app.main.run_document_pipeline"):
        resp = client.post("/api/documents", files=files)

    assert resp.status_code == 200
    res_list = resp.json()
    assert len(res_list) == 1
    item = res_list[0]
    assert item["status"] == "uploading"
    assert item["duplicate"] is False
    doc_id = item["document_id"]
    assert doc_id != ""

    # Mark document as ready in DB so duplicate check catches it
    session = get_session()
    doc = session.get(Document, doc_id)
    doc.status = "ready"
    session.commit()
    session.close()

    # 2. Second upload of the exact same bytes -> duplicate=True
    files2 = [("files", ("guide.pdf", pdf_bytes, "application/pdf"))]
    resp2 = client.post("/api/documents", files=files2)
    assert resp2.status_code == 200
    item2 = resp2.json()[0]
    assert item2["document_id"] == doc_id
    assert item2["duplicate"] is True


def test_api_mixed_upload_good_and_bad(client):
    good_pdf = create_simple_pdf_bytes(["A good valid document."])
    bad_pdf = b"NOT A VALID PDF FILE"

    files = [
        ("files", ("good.pdf", good_pdf, "application/pdf")),
        ("files", ("bad.pdf", bad_pdf, "application/pdf")),
    ]

    with patch("app.main.run_document_pipeline"):
        resp = client.post("/api/documents", files=files)

    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 2
    assert results[0]["status"] == "uploading"
    assert results[0]["error"] is None
    assert results[1]["status"] == "failed"
    assert "missing %PDF- header" in results[1]["error"]


def test_api_document_detail_pages_and_file(client, tmp_path: Path):
    session = get_session()
    doc = Document(
        id="doc-detail-test",
        filename="manual.pdf",
        sha256="1234567890abcdef",
        size_bytes=1024,
        page_count=2,
        status="ready",
        stored_name="test_stored.pdf",
        warnings_json=json.dumps(["Minor warning"]),
        summary_json=json.dumps({"overview": "Manual overview", "suggested_questions": ["Q1?"]}),
    )
    save_document(session, doc)
    save_document_pages(
        session,
        [
            DocumentPage(document_id="doc-detail-test", page_number=1, text="Page 1 text", char_count=11),
            DocumentPage(document_id="doc-detail-test", page_number=2, text="Page 2 text", char_count=11),
        ],
    )
    session.close()

    # Create dummy stored file in upload_dir
    settings = get_settings()
    stored_path = Path(settings.upload_dir) / "test_stored.pdf"
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(b"%PDF-1.4 mock content")

    # 1. GET /api/documents/{id}
    detail_resp = client.get("/api/documents/doc-detail-test")
    assert detail_resp.status_code == 200
    d_data = detail_resp.json()
    assert d_data["filename"] == "manual.pdf"
    assert d_data["page_count"] == 2
    assert d_data["warnings"] == ["Minor warning"]
    assert d_data["summary"]["overview"] == "Manual overview"

    # 2. GET /api/documents/{id}/pages/1
    p1_resp = client.get("/api/documents/doc-detail-test/pages/1")
    assert p1_resp.status_code == 200
    assert p1_resp.json()["text"] == "Page 1 text"

    # 3. GET /api/documents/{id}/pages/99 (404)
    p_none = client.get("/api/documents/doc-detail-test/pages/99")
    assert p_none.status_code == 404

    # 4. GET /api/documents/{id}/file
    f_resp = client.get("/api/documents/doc-detail-test/file")
    assert f_resp.status_code == 200
    assert f_resp.headers["content-type"] == "application/pdf"
    assert f_resp.headers["x-content-type-options"] == "nosniff"

    # 5. DELETE /api/documents/{id}
    del_resp = client.delete("/api/documents/doc-detail-test")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True
    # Confirm DB and disk deletion
    assert not stored_path.exists()
    get_del = client.get("/api/documents/doc-detail-test")
    assert get_del.status_code == 404
