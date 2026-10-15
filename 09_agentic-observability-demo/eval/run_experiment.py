"""Run the agent over a LangSmith dataset and score it. Each run is one "experiment".

Usage:
    python -m eval.run_experiment --dataset rag
    python -m eval.run_experiment --dataset agent --prompt-version v2
    python -m eval.run_experiment --dataset rag --judge     # adds the LLM-as-judge (costs a bit more)

A short summary is saved to eval/results/<experiment name>.json,
so you can compare two runs with eval/compare_runs.py.
"""
import argparse
import json
from dataclasses import replace
from pathlib import Path

from langsmith import Client

from app.agent import build_agent
from app.config import load_settings
from app.logging_setup import setup_logging
from eval.evaluators import AGENT_EVALUATORS, RAG_EVALUATORS, make_llm_judge

DATASET_NAMES = {"rag": "streambox-rag-qa", "agent": "streambox-agent-behaviour"}
RESULTS_DIR = Path(__file__).parent / "results"


def summarise(results):
    """Average score per metric across all examples."""
    totals = {}
    counts = {}
    rows = 0
    for row in results:
        rows += 1
        for result in row["evaluation_results"]["results"]:
            if result.score is None:
                continue
            totals[result.key] = totals.get(result.key, 0.0) + float(result.score)
            counts[result.key] = counts.get(result.key, 0) + 1
    scores = {key: round(totals[key] / counts[key], 3) for key in totals}
    return {"examples": rows, "scores": scores}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=DATASET_NAMES, default="rag")
    parser.add_argument("--prompt-version", help="Override PROMPT_VERSION from .env, e.g. v1 or v2")
    parser.add_argument("--judge", action="store_true", help="Also use an LLM to grade answers.")
    parser.add_argument("--prefix", help="Experiment name prefix. Default: <dataset>-<prompt version>")
    args = parser.parse_args()

    settings = load_settings()
    if args.prompt_version:
        settings = replace(settings, prompt_version=args.prompt_version)
    setup_logging(settings.log_level, settings.log_file)

    agent = build_agent(settings)

    def target(inputs):
        response = agent.ask(inputs["question"])
        return {
            "answer": response.answer,
            "route": response.route,
            "sources": response.sources,
            "contexts": response.contexts,
        }

    evaluators = list(RAG_EVALUATORS if args.dataset == "rag" else AGENT_EVALUATORS)
    if args.judge:
        evaluators.append(make_llm_judge(settings.openai_api_key, settings.openai_model))

    prefix = args.prefix or f"{args.dataset}-{settings.prompt_version}"

    results = Client().evaluate(
        target,
        data=DATASET_NAMES[args.dataset],
        evaluators=evaluators,
        experiment_prefix=prefix,
        metadata={"prompt_version": settings.prompt_version, "model": settings.openai_model, "top_k": settings.top_k},
        max_concurrency=2,
    )

    summary = summarise(results)
    summary["experiment"] = results.experiment_name
    summary["dataset"] = DATASET_NAMES[args.dataset]
    summary["prompt_version"] = settings.prompt_version

    RESULTS_DIR.mkdir(exist_ok=True)
    out_file = RESULTS_DIR / f"{results.experiment_name}.json"
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print()
    print(f"Experiment: {results.experiment_name}")
    for key, score in sorted(summary["scores"].items()):
        print(f"  {key:<15} {score:.2f}")
    print(f"Summary saved to {out_file}")


if __name__ == "__main__":
    main()
