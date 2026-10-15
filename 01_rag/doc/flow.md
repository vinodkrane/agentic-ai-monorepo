# How the RAG Pipeline Works

RAG has two parts:

1. **Ingestion** – load documents and save them in a searchable way. You do this once (or when documents change).
2. **Question answering** – find the best parts of the documents and let the LLM answer from them. This happens for every question.

```
INGESTION
  file ──> parse ──> chunk ──> embed ──> store
           (1)       (2)       (3)       (4)

QUESTION ANSWERING
  question ──> embed ──> search ──> filter ──> LLM ──> answer + sources
               (3)       (5)                   (6)
```

All of this is joined in `rag/pipeline.py` (step 7).

---

## Part 1: Ingestion

Command: `python main.py ingest data/sample_docs`
Code: `RAGPipeline.ingest_folder()` → `ingest_file()` for each file

### Step 1 – Parse (`parser.py`)

We read the file and get plain text.

| File type     | How we read it |
|---------------|----------------|
| `.txt`, `.md` | Read as UTF-8 text |
| `.pdf`        | `pypdf`, one `Page` per PDF page, so we keep page numbers |
| `.docx`       | `python-docx`, join all paragraphs |

Pages with no text are dropped.

### Step 2 – Chunk (`chunker.py`)

LLMs and embeddings work best on small pieces of text. A whole document is too big, and one sentence is too small. So we cut text into **chunks** of about 1000 characters.

How `split_text()` works:

1. Split the text into paragraphs (on blank lines).
2. If one paragraph is bigger than the chunk size, cut it into smaller pieces. We cut between words, never in the middle of a word.
3. Add pieces to the current chunk until the next piece would make it too big. Then start a new chunk.
4. Each new chunk starts with the last ~150 characters of the chunk before it. This is the **overlap**. It helps when an idea is split across two chunks.

Every chunk gets metadata:

```python
{"source": "expenses_policy.pdf", "page": 2, "chunk_index": 1}
```

### Step 3 – Embed (`embedder.py`)

An **embedding** is a list of numbers (a vector) that holds the meaning of a text. Texts with similar meaning get vectors that are close together.

We send the chunk texts to OpenAI in batches of 100 and get one vector back for each chunk.

### Step 4 – Store (`vector_store.py`)

We save each chunk in ChromaDB with:

- an **id** (made from the file name and chunk number, so it is always the same),
- the **text**,
- the **vector**,
- the **metadata**.

Before saving, we **delete the old chunks for that file**. So if you change a file and ingest it again, there are no old or duplicate chunks.

ChromaDB saves everything to the `chroma_db/` folder, so the data is still there after you close the app.

---

## Part 2: Question answering

Command: `python main.py ask "How much leave do I get?"`
Code: `RAGPipeline.ask()`

### Check the input

- An empty question is rejected.
- A very long question (over 2000 characters) is rejected.
- If the database is empty, we say "No documents have been ingested yet." and stop.

### Step 3 again – Embed the question

We turn the question into a vector with the **same** embedding model we used for the chunks. This is important: vectors from different models cannot be compared.

### Step 5 – Search (`vector_store.py`)

ChromaDB finds the `TOP_K` chunks (default 4) whose vectors are closest to the question vector.

We use **cosine** distance. We change it into a simple **score** from 0 to 1:

```
score = 1 - distance      (higher is better)
```

### Filter weak matches (`pipeline.py`)

Chunks with a score below `MIN_RELEVANCE` (default 0.2) are thrown away. If nothing is left, we answer "I could not find this in the documents." and **do not call the LLM**. This saves money and stops made-up answers.

### Step 6 – Generate the answer (`generator.py`)

We build a message for the LLM. The chunks are numbered:

```
Context:

[1] (from leave_policy.md)
Full-time staff get 25 days of paid annual leave each year...

---

[2] (from expenses_policy.pdf, page 2)
...

Question: How much leave do I get?
```

The system prompt tells the LLM to:

- only use the context,
- say "I could not find this in the documents." if the answer is not there,
- add source numbers like `[1]` after each fact.

We use `temperature=0` so the answers are steady and less creative.

### Return the result

`ask()` returns an `Answer`:

```python
Answer(
    text="Full-time staff get 25 days of paid annual leave [1].",
    sources=[{"number": 1, "source": "leave_policy.md", "score": 0.71}],
)
```

The numbers in `sources` match the `[1]`, `[2]` in the answer text.

---

## Step 7 – How it all connects (`pipeline.py`)

```python
pipeline = RAGPipeline(settings)

# Ingestion
pipeline.ingest_folder(Path("data/sample_docs"))
#   for each file:
#     pages      = parse_file(file)
#     chunks     = chunk_pages(pages, ...)
#     embeddings = embedder.embed_texts(chunk texts)
#     vector_store.replace_source(file, chunks, embeddings)

# Question answering
answer = pipeline.ask("How much leave do I get?")
#   query_vector = embedder.embed_query(question)
#   matches      = vector_store.search(query_vector, top_k)
#   matches      = keep only score >= min_relevance
#   text         = generator.generate_answer(question, matches)
```

That is the whole flow. There are no hidden steps.
