"""A short example: ingest the sample documents, then ask a few questions.

Run it with:
    python example.py
"""

from pathlib import Path

from rag.config import load_settings, setup_logging
from rag.pipeline import RAGPipeline

settings = load_settings()
setup_logging(settings.log_level)

pipeline = RAGPipeline(settings)

# 1. Load the documents into the vector database.
pipeline.ingest_folder(Path("data/sample_docs"))

# 2. Ask questions.
questions = [
    "How many days of annual leave do full-time staff get?",
    "What should I do if I lose my laptop?",
    "Can I carry unused leave into next year?",
    "What is the capital of France?",  # Not in the documents. The answer should say so.
]

for question in questions:
    answer = pipeline.ask(question)
    print(f"\nQ: {question}")
    print(f"A: {answer.text}")
    for source in answer.sources:
        print(f"   [{source['number']}] {source['source']} (score {source['score']})")
