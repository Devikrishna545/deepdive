"""Uploaded documents: short notes are kept, unreadable or empty files are refused with a clear message."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import create_app
from app.tools.documents import DocumentError, ingest_document, retrieve


def test_short_note_is_kept(fake_world, tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("Our pilot plant produced 75 units in March 2026.")
    doc = ingest_document(f, "note.txt")
    rows = retrieve([doc.id], "pilot plant output", k=4)
    assert rows and "75 units" in rows[0].text


def test_empty_and_corrupt_files_are_refused(fake_world, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n")
    with pytest.raises(DocumentError, match="no readable text"):
        ingest_document(empty, "empty.txt")
    fake = tmp_path / "fake.pdf"
    fake.write_text("this is not really a pdf")
    with pytest.raises(DocumentError, match="Could not read"):
        ingest_document(fake, "fake.pdf")


def test_upload_api_returns_422_not_500(fake_world):
    with TestClient(create_app()) as c:
        bad = c.post("/api/files", files={"file": ("fake.pdf", b"not a pdf")})
        empty = c.post("/api/files", files={"file": ("empty.txt", b"")})
        ok = c.post("/api/files", files={"file": ("memo.txt", b"Contract covers 450 MWh per year.")})
    assert bad.status_code == 422 and "Could not read" in bad.json()["detail"]
    assert empty.status_code == 422 and "no readable text" in empty.json()["detail"]
    assert ok.status_code == 201
