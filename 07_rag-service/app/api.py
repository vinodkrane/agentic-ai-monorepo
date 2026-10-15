import logging
import os
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import config, status
from app.aws import client
from app.query.graph import build_graph
from app.users import get_groups

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("api")

app = FastAPI(title="kb-rag-service")
graph = build_graph()


class QueryRequest(BaseModel):
    user_id: str
    question: str = Field(min_length=3, max_length=2000)


@app.get("/health")
def health():
    return {"status": "ok"}


def can_see(user_id, doc):
    """Uploader, or anyone in one of the doc's groups."""
    if doc.get("uploaded_by") == user_id:
        return True
    return bool(set(get_groups(user_id)).intersection(doc.get("groups", [])))


@app.post("/documents", status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    groups: str = Form(...),
    user_id: str = Form(...),
    replaces: str = Form(None),
):
    """Upload a doc. Returns a doc_id straight away, indexing happens async:
    S3 -> SQS -> ingest worker (EC2). Poll GET /documents/{doc_id} for progress.

    Pass `replaces=<old doc_id>` to upload a new version of an existing doc.
    The old chunks are removed once the new version is indexed.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"file type {ext} not supported")

    body = await file.read()
    if len(body) == 0:
        raise HTTPException(400, "empty file")
    if len(body) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, "file too large")

    group_list = [g.strip() for g in groups.split(",") if g.strip()]
    if not group_list:
        raise HTTPException(400, "at least one group is required")

    # stop people sharing a doc with groups they aren't in themselves
    not_member = set(group_list) - set(get_groups(user_id))
    if not_member:
        raise HTTPException(403, f"you are not a member of: {', '.join(sorted(not_member))}")

    if replaces:
        old = status.get(replaces)
        if not old or not can_see(user_id, old):
            raise HTTPException(404, "document to replace not found")

    doc_id = uuid.uuid4().hex
    key = f"uploads/{doc_id}/{file.filename}"

    # status row goes in first, a worker can pick the object up within
    # a second of the put and needs the row to exist
    status.create(doc_id, file.filename, key, group_list, user_id, replaces=replaces)

    try:
        client("s3").put_object(
            Bucket=config.DOCS_BUCKET,
            Key=key,
            Body=body,
            # S3 metadata values must be strings
            Metadata={
                "doc-id": doc_id,
                "groups": ",".join(group_list),
                "original-name": file.filename,
                "replaces": replaces or "",
            },
        )
    except Exception:
        log.exception("s3 upload failed for %s", doc_id)
        status.mark_failed(doc_id, "upload to s3 failed")
        raise HTTPException(500, "upload failed, please try again")

    log.info("uploaded doc_id=%s key=%s (%d bytes) groups=%s", doc_id, key, len(body), group_list)
    return {"doc_id": doc_id, "status": status.QUEUED}


@app.get("/documents/{doc_id}")
def document_status(doc_id: str, user_id: str):
    # TODO: user_id should come from the auth header, same as /query
    doc = status.get(doc_id)
    # 404 rather than 403 so we don't confirm the doc exists to people who can't see it
    if not doc or not can_see(user_id, doc):
        raise HTTPException(404, "document not found")

    return {
        "doc_id": doc["doc_id"],
        "status": doc["status"],
        "filename": doc.get("filename"),
        "groups": doc.get("groups", []),
        "chunk_count": int(doc["chunk_count"]) if "chunk_count" in doc else None,
        "error": doc.get("error") or None,
        "replaces": doc.get("replaces"),
        "replaced_by": doc.get("replaced_by"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


@app.post("/query")
def query(req: QueryRequest):
    start = time.time()
    groups = get_groups(req.user_id)
    if not groups:
        raise HTTPException(403, "user has no access to any documents")

    result = graph.invoke({
        "question": req.question,
        "user_id": req.user_id,
        "groups": groups,
        "timings": {},
    })

    total_ms = int((time.time() - start) * 1000)
    log.info("query user=%s total_ms=%d blocked=%s", req.user_id, total_ms, result.get("blocked"))

    return {
        "answer": result.get("answer"),
        "citations": result.get("citations", []),
        "blocked": result.get("blocked", False),
        "timings_ms": {**result.get("timings", {}), "total": total_ms},
    }
