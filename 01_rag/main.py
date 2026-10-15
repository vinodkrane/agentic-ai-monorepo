"""Command line entry point.

Examples:
    python main.py ingest data/sample_docs
    python main.py ask "How many days of annual leave do staff get?"
    python main.py chat
    python main.py stats
"""

import argparse
import logging
import sys
from pathlib import Path

from rag.config import load_settings, setup_logging
from rag.pipeline import Answer, RAGPipeline

logger = logging.getLogger("main")


def print_answer(answer: Answer) -> None:
    print(f"\n{answer.text}\n")
    if answer.sources:
        print("Sources:")
        for source in answer.sources:
            print(f"  [{source['number']}] {source['source']} (score {source['score']})")
    print()


def run_chat(pipeline: RAGPipeline) -> None:
    print("Ask a question. Type 'exit' to quit.")
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if question.lower() in ("exit", "quit"):
            break
        if not question:
            continue
        try:
            print_answer(pipeline.ask(question))
        except Exception as error:
            logger.error("Could not answer: %s", error)


def main() -> int:
    parser = argparse.ArgumentParser(description="Simple RAG pipeline")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="Load documents from a folder or a single file")
    ingest.add_argument("path", type=Path)

    ask = commands.add_parser("ask", help="Ask one question")
    ask.add_argument("question")

    commands.add_parser("chat", help="Ask questions in a loop")
    commands.add_parser("stats", help="Show what is stored in the database")

    args = parser.parse_args()

    try:
        settings = load_settings()
        setup_logging(settings.log_level)
        pipeline = RAGPipeline(settings)

        if args.command == "ingest":
            if args.path.is_file():
                pipeline.ingest_file(args.path)
            else:
                summary = pipeline.ingest_folder(args.path)
                if summary["files_failed"]:
                    return 1
        elif args.command == "ask":
            print_answer(pipeline.ask(args.question))
        elif args.command == "chat":
            run_chat(pipeline)
        elif args.command == "stats":
            sources = pipeline.vector_store.list_sources()
            print(f"Chunks stored: {pipeline.vector_store.count()}")
            print(f"Documents ({len(sources)}):")
            for source in sources:
                print(f"  - {source}")
    except Exception as error:
        logging.getLogger("main").error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
