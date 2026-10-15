"""Ingest local files straight into OpenSearch, skipping S3/SQS/status table.

Handy for local dev and for seeding the eval index.

    python -m scripts.local_ingest --groups all-staff data/sample_docs/expenses-policy.md
"""
import argparse
import hashlib
import logging
import os

from app.embeddings import embed_many
from app.ingest import indexer
from app.ingest.chunker import make_chunks
from app.ingest.parser import parse

logging.basicConfig(level=logging.INFO)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--groups", required=True, help="comma separated, e.g. all-staff,platform-eng")
    args = ap.parse_args()

    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    indexer.ensure_index()

    for path in args.files:
        with open(path, "rb") as f:
            data = f.read()
        name = os.path.basename(path)
        doc_id = hashlib.sha1(f"local/{name}".encode()).hexdigest()[:16]

        pages = parse(name, data)
        chunks = make_chunks(doc_id, name, pages, groups)
        vectors = embed_many([c["text"] for c in chunks])
        indexer.delete_doc(doc_id)
        n = indexer.index_chunks(chunks, vectors)
        print(f"{name}: {n} chunks")


if __name__ == "__main__":
    main()
