"""Files API: upload a PDF / DOCX / TXT to ground research in your own documents."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.config import get_settings
from app.core.utils import new_id
from app.llm.billing import InsufficientBalance, require_balance
from app.routes.guards import require_access_code
from app.tools.documents import ALLOWED_SUFFIXES, DocumentError, ingest_document

router = APIRouter()

MAX_BYTES = 20 * 1024 * 1024


@router.post("", status_code=201, dependencies=[Depends(require_access_code)])
def upload_file(file: UploadFile) -> dict:
    try:
        require_balance()  # embedding the document spends credits
    except InsufficientBalance as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    name = Path(file.filename or "upload").name  # strip any client-side path
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail=f"allowed types: {sorted(ALLOWED_SUFFIXES)}")
    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{new_id('up')}{suffix}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    if dest.stat().st_size > MAX_BYTES:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail="file larger than 20 MB")
    try:
        doc = ingest_document(dest, name)
    except DocumentError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"file_id": doc.id, "filename": doc.filename, "pages": doc.pages}
