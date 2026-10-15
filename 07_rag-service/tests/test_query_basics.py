from app.query import guardrails
from app.query.acl import acl_filter
from app.query.fusion import rrf


def hit(cid, groups=("all-staff",)):
    return {"chunk_id": cid, "text": cid, "allowed_groups": list(groups)}


def test_rrf_rewards_chunks_in_both_lists():
    bm25 = [hit("a"), hit("b"), hit("c")]
    knn = [hit("c"), hit("d"), hit("a")]
    fused = [h["chunk_id"] for h in rrf([bm25, knn], k=60)]
    # a and c show up in both so they should be on top
    assert set(fused[:2]) == {"a", "c"}
    assert len(fused) == 4


def test_rrf_empty():
    assert rrf([[], []]) == []


def test_acl_drops_chunks_from_other_groups():
    chunks = [hit("a"), hit("b", ["platform-eng"]), hit("c", ["platform-eng", "all-staff"])]
    kept = [c["chunk_id"] for c in acl_filter(chunks, ["all-staff"])]
    assert kept == ["a", "c"]


def test_acl_no_groups_sees_nothing():
    assert acl_filter([hit("a")], []) == []


def test_pii_detection():
    assert "email" in guardrails.find_pii("contact jane.doe@example.com")
    assert "uk_phone" in guardrails.find_pii("call 07700 900123")
    assert "ni_number" in guardrails.find_pii("NI: AB 12 34 56 C")
    assert guardrails.find_pii("how many days leave do I get") == []


def test_redact():
    out = guardrails.redact_pii("mail jane.doe@example.com or 07700 900123")
    assert "jane.doe" not in out
    assert "[EMAIL]" in out and "[UK_PHONE]" in out


def test_toxic():
    assert guardrails.is_toxic("just KYS")
    assert not guardrails.is_toxic("what is the hotel limit")
