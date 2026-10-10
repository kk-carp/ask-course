import asyncio
import threading
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import documents
from backend.services.auth_service import AuthContext, AuthUser
from backend.services.ingest_service import DocumentResult


def document_app():
    app = FastAPI()
    app.include_router(documents.router)

    @app.get("/health")
    async def health():
        return {"api": True}

    return app


@pytest.mark.parametrize("role, expected", [(None, 401), ("teaching", 403), ("student", 403)])
@pytest.mark.parametrize("method, url, payload", [
    ("GET", "/documents", {}),
    ("GET", "/documents/one/inspection", {}),
    ("POST", "/documents", {"data": {"space": "courses"}, "files": {"file": ("course.md", b"text")}}),
    ("POST", "/documents/one/offline", {}),
    ("DELETE", "/documents/one", {}),
    ("POST", "/documents/batch-offline", {"json": {"ids": ["one"]}}),
    ("POST", "/documents/batch-delete", {"json": {"ids": ["one"]}}),
    ("POST", "/documents/one/publish", {"json": {"note": "reviewed"}}),
    ("POST", "/documents/one/review", {"json": {"note": "reviewed"}}),
])
def test_document_maintenance_requires_admin(monkeypatch, role, expected, method, url, payload):
    context = AuthContext(AuthUser(id="test", username="test", role=role), ["courses"]) if role else None
    monkeypatch.setattr(documents, "load_auth_context", lambda _request: context)

    def unexpected(*_args, **_kwargs):
        pytest.fail("Unauthorized request reached document storage")

    for name in ("list_documents", "ingest_document", "set_document_offline", "delete_offline_document",
                 "set_documents_offline", "delete_offline_documents", "publish_document", "inspect_document"):
        monkeypatch.setattr(documents, name, unexpected)
    response = TestClient(document_app()).request(method, url, **payload)
    assert response.status_code == expected


def test_slow_document_upload_does_not_block_other_requests(monkeypatch):
    started, release = threading.Event(), threading.Event()
    context = AuthContext(AuthUser(id="admin", username="admin", role="admin"), ["courses"])
    monkeypatch.setattr(documents, "load_auth_context", lambda _request: context)

    def ingest(*, file, space_id, replace, course_id):
        assert file.file.read() == b"course content"
        assert (space_id, replace, course_id) == ("courses", False, "42")
        started.set()
        # Bound even a regressed implementation so the test cannot hang the suite.
        release.wait(timeout=2)
        return DocumentResult(id=uuid4(), title=file.filename, space_id=space_id,
                              course_id=course_id, status="ready", chunk_count=1)

    monkeypatch.setattr(documents, "ingest_document", ingest)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=document_app()), base_url="http://test") as client:
            pending = asyncio.create_task(client.post("/documents", data={"space": "courses", "course_id": "42"},
                                                      files={"file": ("course.md", b"course content")}))
            try:
                for _ in range(200):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.005)
                assert started.is_set(), "Upload never reached ingestion"
                response = await asyncio.wait_for(client.get("/health"), timeout=1)
                assert response.json() == {"api": True}
                assert not pending.done(), "Ingestion blocked the event loop until upload completion"
            finally:
                release.set()
                response = await pending
            assert response.status_code == 201
            assert response.json()["course_id"] == "42"

    asyncio.run(scenario())
