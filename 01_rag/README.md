# Simple RAG

A small, clean RAG (Retrieval-Augmented Generation) app in Python.

You give it documents. You ask questions. It finds the right parts of your documents and uses an LLM to write an answer, with sources.

```
documents -> parse -> chunk -> embed -> store in ChromaDB
question  -> embed -> search ChromaDB -> send best chunks to LLM -> answer
```

## What it uses

| Part           | Tool                                    |
|----------------|-----------------------------------------|
| LLM            | OpenAI chat model (`gpt-4o-mini`)       |
| Embeddings     | OpenAI (`text-embedding-3-small`)       |
| Vector database| ChromaDB (saved on your disk)           |
| File reading   | `pypdf` for PDF, `python-docx` for Word |

Supported files: `.txt`, `.md`, `.pdf`, `.docx`

## Setup

You need **Python 3.10 or newer** and an **OpenAI API key**.

```bash
# 1. Go into the project folder
cd simple-rag

# 2. Make a virtual environment
python -m venv .venv
source .venv/bin/activate        # On Windows: .venv\Scripts\activate

# 3. Install the packages
pip install -r requirements.txt

# 4. Make your settings file and add your API key
cp .env.example .env
# now open .env and set OPENAI_API_KEY
```

## Usage

### Quick example

This loads the sample documents in `data/sample_docs/` and asks four questions:

```bash
python example.py
```

### Command line

```bash
# Load all documents in a folder
python main.py ingest data/sample_docs

# Load one file
python main.py ingest path/to/file.pdf

# Ask one question
python main.py ask "How many days of annual leave do full-time staff get?"

# Ask many questions, one after another
python main.py chat

# See what is in the database
python main.py stats
```

Example output:

```
Full-time staff get 25 days of paid annual leave each year, on top of public holidays [1].

Sources:
  [1] leave_policy.md (score 0.71)
```

### Use it from your own Python code

```python
from pathlib import Path
from rag.config import load_settings, setup_logging
from rag.pipeline import RAGPipeline

settings = load_settings()
setup_logging(settings.log_level)
pipeline = RAGPipeline(settings)

pipeline.ingest_folder(Path("my_documents"))
answer = pipeline.ask("What is our refund policy?")
print(answer.text)
print(answer.sources)
```

## Configuration

All settings live in the `.env` file. Only `OPENAI_API_KEY` is required.

| Setting           | Default                  | What it does |
|-------------------|--------------------------|--------------|
| `OPENAI_API_KEY`  | (none)                   | Your OpenAI key. Required. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Model that turns text into vectors. |
| `CHAT_MODEL`      | `gpt-4o-mini`            | Model that writes the answer. |
| `DB_PATH`         | `./chroma_db`            | Folder where ChromaDB saves data. |
| `COLLECTION_NAME` | `documents`              | Name of the collection inside ChromaDB. |
| `CHUNK_SIZE`      | `1000`                   | Max characters in one chunk. |
| `CHUNK_OVERLAP`   | `150`                    | Characters shared between two chunks next to each other. |
| `TOP_K`           | `4`                      | How many chunks to send to the LLM. |
| `MIN_RELEVANCE`   | `0.2`                    | Chunks with a lower score (0 to 1) are ignored. |
| `LOG_LEVEL`       | `INFO`                   | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |

**Important:** if you change `EMBEDDING_MODEL`, delete the `chroma_db` folder and ingest again. Vectors from different models cannot be mixed.

## Running the tests

The tests do not call OpenAI, so they need no API key and cost nothing.

```bash
pip install -r requirements-dev.txt
pytest
```

## Good to know

- Running `ingest` again on the same file **replaces** its old chunks. It does not make copies.
- If one file fails (for example, a broken PDF), the others are still loaded. The error is shown in the log.
- Scanned PDFs (pictures of text) have no text to read. They are skipped with a warning.
- If the documents do not have the answer, the app says so. It does not make up an answer.

## More docs

- [doc/project_structure.md](doc/project_structure.md) – what each file does
- [doc/flow.md](doc/flow.md) – how the pipeline works, step by step
- [doc/issues_faced.md](doc/issues_faced.md) – common problems and how to fix them
