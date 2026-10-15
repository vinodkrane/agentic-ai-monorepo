# Project Structure

```
simple-rag/
├── rag/                     # The main code
│   ├── __init__.py
│   ├── config.py            # Settings and logging
│   ├── parser.py            # Step 1: read files
│   ├── chunker.py           # Step 2: split text into chunks
│   ├── embedder.py          # Step 3: turn text into vectors
│   ├── vector_store.py      # Step 4 and 5: save and search in ChromaDB
│   ├── generator.py         # Step 6: write the answer with the LLM
│   └── pipeline.py          # Step 7: join all the steps
├── tests/                   # Tests (no API key needed)
│   ├── conftest.py          # Fake embedder, fake LLM, test settings
│   ├── test_parser.py
│   ├── test_chunker.py
│   ├── test_pipeline.py
│   └── test_openai_parts.py
├── data/
│   └── sample_docs/         # Example files: .md, .txt, .pdf, .docx
├── doc/                     # Extra documentation (you are here)
├── main.py                  # Command line tool
├── example.py               # Short demo: ingest, then ask questions
├── requirements.txt         # Packages needed to run
├── requirements-dev.txt     # Packages needed to run the tests
├── .env.example             # Example settings. Copy to .env
├── .gitignore
└── README.md
```

## The `rag/` folder

Each file does **one** job. Each job is one step of the pipeline. You can read them in order, from top to bottom.

### `config.py`
- Reads settings from the `.env` file and environment variables.
- Checks the settings make sense (for example, overlap must be smaller than chunk size).
- Sets up logging in one place, so all files log in the same format.

### `parser.py`
- `parse_file()` reads one file and returns a list of `Page` objects.
- A `Page` is some text, the file name, and (for PDFs) the page number.
- `find_files()` finds all supported files in a folder.
- To support a new file type, add one small function here.

### `chunker.py`
- `split_text()` cuts long text into smaller chunks.
- `chunk_pages()` runs `split_text()` on each page and adds metadata (source, page, chunk number).

### `embedder.py`
- The `Embedder` class calls the OpenAI API to turn text into vectors.
- It sends texts in batches of 100, which is much faster than one at a time.

### `vector_store.py`
- The `VectorStore` class wraps ChromaDB.
- `replace_source()` deletes old chunks of a file, then adds the new ones.
- `search()` finds the closest chunks to a query vector and gives each one a score from 0 to 1.

### `generator.py`
- Holds the system prompt for the LLM.
- `build_context()` turns the chunks into numbered blocks: `[1]`, `[2]`, ...
- The `Generator` class calls the chat model and returns the answer.

### `pipeline.py`
- `RAGPipeline` connects everything.
- `ingest_file()` and `ingest_folder()` load documents.
- `ask()` answers a question and returns an `Answer` with the text and sources.
- You can pass your own embedder, generator or vector store. The tests use this to swap in fakes.

## Other files

### `main.py`
The command line tool. Commands: `ingest`, `ask`, `chat`, `stats`. It catches errors and prints a clear message instead of a long stack trace.

### `example.py`
The quickest way to see the app work. It loads the sample docs and asks four questions. One question is not in the docs, to show the app says "I could not find this".

### `tests/`
Tests use a **fake embedder** (counts words) and a **fake LLM**. This means:
- no API key is needed,
- tests are fast and free,
- the real ChromaDB is still used, in a temporary folder.

### `chroma_db/` (made when you run the app)
ChromaDB saves its data here. It is in `.gitignore`. Delete it to start fresh.
