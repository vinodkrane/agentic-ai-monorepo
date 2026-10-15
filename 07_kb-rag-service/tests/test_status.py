from app import status


def new_doc(doc_id="d1"):
    status.create(doc_id, "leave.md", f"uploads/{doc_id}/leave.md", ["all-staff"], "bob")


def test_create_and_get(aws):
    new_doc()
    doc = status.get("d1")
    assert doc["status"] == "queued"
    assert doc["groups"] == ["all-staff"]
    assert doc["uploaded_by"] == "bob"


def test_happy_path(aws):
    new_doc()
    assert status.start_processing("d1", 1)
    assert status.mark_completed("d1", 12)
    doc = status.get("d1")
    assert doc["status"] == "completed"
    assert doc["chunk_count"] == 12


def test_duplicate_message_cant_reprocess_completed_doc(aws):
    new_doc()
    status.start_processing("d1", 1)
    status.mark_completed("d1", 3)

    assert status.start_processing("d1", 2) is False
    assert status.get("d1")["status"] == "completed"


def test_failed_can_be_redriven(aws):
    new_doc()
    status.start_processing("d1", 3)
    status.mark_failed("d1", "ThrottlingException")
    assert status.get("d1")["error"] == "ThrottlingException"

    # message redriven from the DLQ
    assert status.start_processing("d1", 1)
    assert status.get("d1")["error"] == ""


def test_cant_fail_a_completed_doc(aws):
    new_doc()
    status.start_processing("d1", 1)
    status.mark_completed("d1", 3)
    assert status.mark_failed("d1", "late error") is False


def test_unknown_doc_is_noop(aws):
    assert status.start_processing("nope", 1) is False


def test_replaced(aws):
    new_doc("old")
    status.start_processing("old", 1)
    status.mark_completed("old", 3)
    assert status.mark_replaced("old", "new")
    assert status.get("old")["replaced_by"] == "new"


def test_find_stuck(aws):
    new_doc("a")
    new_doc("b")
    status.start_processing("a", 1)
    status.start_processing("b", 1)
    status.mark_completed("b", 1)

    assert [d["doc_id"] for d in status.find_stuck(older_than_minutes=0)] == ["a"]
    assert status.find_stuck(older_than_minutes=60) == []
