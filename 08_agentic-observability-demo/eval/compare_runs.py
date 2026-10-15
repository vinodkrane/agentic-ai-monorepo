"""Compare two experiment summaries and flag metrics that got worse.

Usage:
    python -m eval.compare_runs eval/results/<old>.json eval/results/<new>.json

Exit code 1 means at least one metric dropped by more than the tolerance,
so you can use this in a CI pipeline.
"""
import argparse
import json
import sys


def compare_scores(old_scores, new_scores, tolerance=0.05):
    """Return one row per metric: (metric, old, new, change, status)."""
    rows = []
    for metric in sorted(set(old_scores) | set(new_scores)):
        old = old_scores.get(metric)
        new = new_scores.get(metric)
        if old is None or new is None:
            rows.append((metric, old, new, None, "NEW" if old is None else "REMOVED"))
            continue
        change = round(new - old, 3)
        if change < -tolerance:
            status = "WORSE"
        elif change > tolerance:
            status = "BETTER"
        else:
            status = "SAME"
        rows.append((metric, old, new, change, status))
    return rows


def _fmt(value):
    return "-" if value is None else f"{value:.2f}"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("old_file")
    parser.add_argument("new_file")
    parser.add_argument("--tolerance", type=float, default=0.05)
    args = parser.parse_args(argv)

    with open(args.old_file, encoding="utf-8") as f:
        old = json.load(f)
    with open(args.new_file, encoding="utf-8") as f:
        new = json.load(f)

    print(f"old: {old.get('experiment')}")
    print(f"new: {new.get('experiment')}\n")
    print(f"{'metric':<16}{'old':>6}{'new':>6}{'change':>8}  status")

    rows = compare_scores(old["scores"], new["scores"], args.tolerance)
    for metric, old_score, new_score, change, status in rows:
        print(f"{metric:<16}{_fmt(old_score):>6}{_fmt(new_score):>6}{_fmt(change):>8}  {status}")

    if any(row[4] == "WORSE" for row in rows):
        print("\nQuality went down. Look at the experiments side by side in LangSmith.")
        return 1
    print("\nNo metric got worse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
