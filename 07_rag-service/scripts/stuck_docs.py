"""List docs stuck in "processing" (worker killed mid run, instance terminated etc.)

    python -m scripts.stuck_docs            # default STUCK_AFTER_MINUTES
    python -m scripts.stuck_docs --minutes 5
    python -m scripts.stuck_docs --mark-failed

--mark-failed sets them to failed so the uploader sees something useful.
If the SQS message is still around it will retry and move them back to
processing, that's fine.
"""
import argparse

from app import config, status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=config.STUCK_AFTER_MINUTES)
    ap.add_argument("--mark-failed", action="store_true")
    args = ap.parse_args()

    stuck = status.find_stuck(args.minutes)
    if not stuck:
        print("nothing stuck")
        return

    for doc in stuck:
        print(f"{doc['doc_id']}  {doc.get('filename')}  updated={doc['updated_at']}  attempts={doc.get('attempts')}")
        if args.mark_failed:
            status.mark_failed(doc["doc_id"], f"stuck in processing for over {args.minutes} minutes")

    print(f"{len(stuck)} stuck")


if __name__ == "__main__":
    main()
