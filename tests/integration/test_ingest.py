"""Replacement must preserve usable knowledge until the candidate is ready."""

from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import UploadFile
from sqlalchemy import select

from backend.config import settings
from backend.models import Chunk, Document
from backend.services import ingest_service as ingest
from backend.services.document_admin_service import DocumentDeleteError, publish_document, set_document_offline
from backend.services.material_safety import REVIEW_CHECKS


@pytest.fixture
def ingest_store(postgres_store, monkeypatch, tmp_path):
    factory, _, _ = postgres_store
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "course_content_validation_mode", "off")
    monkeypatch.setattr(ingest, "is_loaded", lambda: True)
    monkeypatch.setattr(ingest, "encode_documents", lambda chunks: [[1.0] + [0.0] * 1023 for _ in chunks])
    return factory


def upload(*, replace=False, name="course.txt"):
    with BytesIO(b"robot hardware syllabus") as content:
        result = ingest.ingest_document(UploadFile(filename=name, file=content), "courses",
                                       replace=replace, course_id="43")
    if not replace:
        return publish_document(str(result.id), actor_id="reviewer", note="Test course reviewed", safety_checks=dict.fromkeys(REVIEW_CHECKS, True))
    return result


@pytest.mark.parametrize("failure", ["save", "parse", "embedding", "persist"])
def test_failed_replacement_keeps_old_document_retrievable(ingest_store, monkeypatch, failure):
    old = upload()

    def fail(*_args, **_kwargs):
        raise RuntimeError("candidate failed")

    monkeypatch.setattr(ingest, {"save": "save_upload", "parse": "parse_document",
                                "embedding": "encode_documents", "persist": "update_chunk_content_tsv"}[failure], fail)
    with pytest.raises(RuntimeError, match="candidate failed"):
        upload(replace=True)
    with ingest_store() as session:
        assert session.get(Document, str(old.id)).status == "ready"
        ready = list(session.scalars(select(Document).where(Document.status == "ready")))
        assert [row.id for row in ready] == [str(old.id)]
        assert len(list(session.scalars(select(Chunk).where(Chunk.document_id == str(old.id))))) == 1
        for candidate in session.scalars(select(Document).where(Document.id != str(old.id))):
            assert candidate.status == "failed"
            assert not list(session.scalars(select(Chunk).where(Chunk.document_id == candidate.id)))


def test_successful_replacement_has_no_knowledge_gap(ingest_store, monkeypatch):
    old = upload()
    parse = ingest.parse_document

    def inspect_old(*args):
        with ingest_store() as session:
            assert session.get(Document, str(old.id)).status == "ready"
        return parse(*args)

    monkeypatch.setattr(ingest, "parse_document", inspect_old)
    new = upload(replace=True)
    with ingest_store() as session:
        assert session.get(Document, str(old.id)).status == "ready"
        assert session.get(Document, str(new.id)).status == "pending"
    publish_document(str(new.id), actor_id="reviewer", note="Replacement reviewed", safety_checks=dict.fromkeys(REVIEW_CHECKS, True))
    with ingest_store() as session:
        assert session.get(Document, str(old.id)).status == "offline"
        assert session.get(Document, str(new.id)).status == "ready"
    with pytest.raises(ingest.DuplicateDocumentError):
        upload()


def test_withdrawal_during_replacement_is_not_undone(ingest_store, monkeypatch):
    old = upload()
    parse = ingest.parse_document

    def withdraw(*args):
        with ingest_store() as session:
            session.get(Document, str(old.id)).status = "offline"
            session.commit()
        return parse(*args)

    monkeypatch.setattr(ingest, "parse_document", withdraw)
    candidate = upload(replace=True)
    with pytest.raises(DocumentDeleteError, match="原资料已变化"):
        publish_document(str(candidate.id), actor_id="reviewer", note="reviewed", safety_checks=dict.fromkeys(REVIEW_CHECKS, True))
    with ingest_store() as session:
        assert not list(session.scalars(select(Document).where(Document.status == "ready")))


def test_concurrent_duplicate_upload_returns_conflict(ingest_store, monkeypatch):
    barrier = Barrier(2)
    save = ingest.save_upload

    def save_together(*args):
        barrier.wait(timeout=5)
        return save(*args)

    monkeypatch.setattr(ingest, "save_upload", save_together)

    def attempt():
        try:
            upload()
            return 201
        except ingest.DuplicateDocumentError as exc:
            assert exc.space_id == "courses"
            return 409

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert sorted(future.result(timeout=10) for future in futures) == [201, 409]
    with ingest_store() as session:
        assert len(list(session.scalars(select(Document)))) == 1


def test_concurrent_replacements_publish_only_one_candidate(ingest_store, monkeypatch):
    old = upload()
    barrier = Barrier(2)
    parse = ingest.parse_document

    def parse_together(*args):
        barrier.wait(timeout=5)
        return parse(*args)

    monkeypatch.setattr(ingest, "parse_document", parse_together)

    def attempt():
        try:
            return upload(replace=True).status
        except ingest.DuplicateDocumentError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert sorted(future.result(timeout=10) for future in futures) == ["conflict", "pending"]
    with ingest_store() as session:
        assert session.get(Document, str(old.id)).status == "ready"
        assert len(list(session.scalars(select(Document).where(Document.status == "ready")))) == 1
        assert len(list(session.scalars(select(Document).where(Document.status == "failed")))) == 1
