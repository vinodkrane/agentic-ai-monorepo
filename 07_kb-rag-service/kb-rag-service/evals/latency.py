"""Latency eval: TTFT, tokens/sec, retrieval and end to end time.

Runs every answerable golden question a few times through the graph and
prints p50/p95. Exits non zero if we're over budget so CI can fail on it.

    python -m evals.latency --runs 3
"""
import argparse
import statistics
import sys
import time

from evals.common import LATENCY_BUDGET, load_golden, run


def pct(values, p):
    if not values:
        return 0
    values = sorted(values)
    idx = min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))
    return values[idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    rows = [r for r in load_golden() if r["expected_sources"]]
    ttft, tps, retrieve, rerank, total = [], [], [], [], []

    # first call loads the reranker + opens connections, don't count it
    run(rows[0]["question"], rows[0]["user_id"])

    for _ in range(args.runs):
        for row in rows:
            start = time.perf_counter()
            result = run(row["question"], row["user_id"])
            total.append((time.perf_counter() - start) * 1000)

            t = result.get("timings", {})
            if "ttft" in t:
                # ttft from the user's point of view = everything before the llm + llm ttft
                ttft.append(t.get("retrieve", 0) + t.get("rerank", 0) + t["ttft"])
                tps.append(t["tps"])
            retrieve.append(t.get("retrieve", 0))
            rerank.append(t.get("rerank", 0))

    report = {
        "ttft_p50_ms": pct(ttft, 50),
        "ttft_p95_ms": pct(ttft, 95),
        "tps_p50": statistics.median(tps) if tps else 0,
        "retrieve_p95_ms": pct(retrieve, 95),
        "rerank_p95_ms": pct(rerank, 95),
        "total_p50_ms": pct(total, 50),
        "total_p95_ms": pct(total, 95),
    }
    print(f"samples={len(total)}")
    for k, v in report.items():
        print(f"  {k:18} {v:.0f}")

    failed = []
    if report["ttft_p95_ms"] > LATENCY_BUDGET["ttft_p95_ms"]:
        failed.append("ttft_p95")
    if report["total_p95_ms"] > LATENCY_BUDGET["total_p95_ms"]:
        failed.append("total_p95")
    if report["retrieve_p95_ms"] > LATENCY_BUDGET["retrieve_p95_ms"]:
        failed.append("retrieve_p95")
    if report["tps_p50"] < LATENCY_BUDGET["tps_p50_min"]:
        failed.append("tps_p50")

    if failed:
        print("OVER BUDGET:", ", ".join(failed))
        sys.exit(1)
    print("within budget")


if __name__ == "__main__":
    main()
