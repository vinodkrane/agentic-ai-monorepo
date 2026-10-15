"""Command line entry point.

Usage:
    python -m app.cli "How long do I have to ask for a refund?"
"""
import argparse
import sys

from app.agent import AgentError, build_agent
from app.config import load_settings
from app.llm import LLMError
from app.logging_setup import setup_logging
from app.validation import ValidationError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ask the StreamBox support agent a question.")
    parser.add_argument("question", nargs="?", help="Your question. If empty you will be asked for it.")
    args = parser.parse_args(argv)

    settings = load_settings()
    setup_logging(settings.log_level, settings.log_file)

    try:
        agent = build_agent(settings)
    except (LLMError, FileNotFoundError) as exc:
        print(f"Setup error: {exc}")
        return 1

    question = args.question if args.question is not None else input("Ask a question: ")

    try:
        response = agent.ask(question)
    except ValidationError as exc:
        print(f"Invalid question: {exc}")
        return 2
    except AgentError as exc:
        print(f"Error: {exc}")
        return 1

    print()
    print(response.answer)
    print()
    print(f"route:      {response.route}")
    print(f"sources:    {', '.join(response.sources) or '-'}")
    print(f"tokens:     {response.input_tokens} in / {response.output_tokens} out")
    print(f"latency:    {response.latency_ms} ms")
    print(f"request id: {response.request_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
