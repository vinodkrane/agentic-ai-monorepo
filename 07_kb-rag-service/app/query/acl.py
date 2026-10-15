import logging

log = logging.getLogger(__name__)


def acl_filter(chunks, user_groups):
    """Second ACL check after retrieval.

    OpenSearch already filters by group, this is belt and braces in case a
    query is changed later and someone forgets the filter. If this ever
    drops anything it's a bug upstream, so log it loudly.
    """
    allowed = set(user_groups)
    kept = []
    for c in chunks:
        if allowed.intersection(c.get("allowed_groups", [])):
            kept.append(c)
        else:
            log.error("ACL re-check dropped chunk %s - retrieval filter missed it", c.get("chunk_id"))
    return kept
