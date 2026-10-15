import pytest
from fastapi.testclient import TestClient

from app import config, status
from app.api import app


@pytest.fixture
def api(aws):
    return TestClient(app)


def post_doc(api, user="alice", groups="all-staff", name="leave.md", body=b"some text", **extra):
    return api.post(
        "/documents",
        files={"file": (name, body)},
        data={"groups": groups, "user_id": user, **extra},
    )


def test_upload_returns_doc_id_and_queued(api, aws):
    r = post_doc(api)
    assert r.status_code == 202
    doc_id = r.json()["doc_id"]
    assert r.json()["status"] == "queued"

    head = aws.head_object(Bucket=config.DOCS_BUCKET, Key=f"uploads/{doc_id}/leave.md")
    assert head["Metadata"]["doc-id"] == doc_id
    assert head["Metadata"]["groups"] == "all-staff"


def test_status_endpoint(api):
    doc_id = post_doc(api).json()["doc_id"]
    r = api.get(f"/documents/{doc_id}", params={"user_id": "bob"})  # bob is in all-staff
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    assert r.json()["filename"] == "leave.md"


def test_status_shows_completed(api):
    doc_id = post_doc(api).json()["doc_id"]
    status.start_processing(doc_id, 1)
    status.mark_completed(doc_id, 7)

    body = api.get(f"/documents/{doc_id}", params={"user_id": "alice"}).json()
    assert body["status"] == "completed"
    assert body["chunk_count"] == 7


def test_status_hidden_from_other_groups(api):
    doc_id = post_doc(api, groups="platform-eng").json()["doc_id"]
    assert api.get(f"/documents/{doc_id}", params={"user_id": "bob"}).status_code == 404
    assert api.get(f"/documents/{doc_id}", params={"user_id": "alice"}).status_code == 200


def test_unknown_doc_404(api):
    assert api.get("/documents/nope", params={"user_id": "alice"}).status_code == 404


def test_cant_share_with_group_you_are_not_in(api):
    r = post_doc(api, user="bob", groups="platform-eng")
    assert r.status_code == 403


def test_bad_extension(api):
    assert post_doc(api, name="virus.exe").status_code == 400


def test_replaces_must_exist(api):
    r = post_doc(api, replaces="does-not-exist")
    assert r.status_code == 404


def test_replace_existing(api):
    old_id = post_doc(api).json()["doc_id"]
    r = post_doc(api, replaces=old_id)
    assert r.status_code == 202
    new = api.get(f"/documents/{r.json()['doc_id']}", params={"user_id": "alice"}).json()
    assert new["replaces"] == old_id
