# Issues Faced and How to Fix Them

This page lists common problems when building and running a RAG app, and what we did (or what you can do) about each one.

---

## Setup problems

### "OPENAI_API_KEY is not set"
**Why:** There is no `.env` file, or the key is empty.
**Fix:** Run `cp .env.example .env` and put your key in it. Run the command from the project folder, because `.env` is read from the current folder.

### ChromaDB will not install
**Why:** ChromaDB needs some compiled packages. Very old or very new Python versions may not have them yet.
**Fix:** Use Python 3.10 to 3.12 if you have trouble. Update pip first: `pip install --upgrade pip`.

### `ModuleNotFoundError: No module named 'rag'`
**Why:** You ran a script from another folder.
**Fix:** Run `python main.py ...` from inside the `simple-rag` folder.

---

## Parsing problems

### A PDF gives no text
**Why:** The PDF is a scan (a picture of text). There is no text inside to read.
**What we do:** Empty pages are skipped and a warning is logged.
**Fix:** Run OCR on the file first (for example with `ocrmypdf`), then ingest the new file.

### PDF text looks broken (missing spaces, odd order)
**Why:** PDFs store text by position on the page, not as sentences. Tables and multi-column pages are hard to read in the right order.
**Fix:** Check the text with `python -c "from rag.parser import parse_file; from pathlib import Path; print(parse_file(Path('file.pdf'))[0].text)"`. If it is very bad, try another PDF library like `pymupdf`, or convert the file to `.docx` or `.md` first.

### Strange characters in `.txt` files
**Why:** The file is not UTF-8.
**What we do:** We read with `errors="replace"`, so the app does not crash. Bad characters become `�`.
**Fix:** Save the file as UTF-8.

### Tables inside `.docx` files are missing
**Why:** We only read paragraphs, to keep the parser simple.
**Fix:** If you need tables, add a loop over `document.tables` in `_parse_docx()`.

---

## Chunking problems

### Answers miss part of the information
**Why:** The answer was split across two chunks, and only one chunk was found.
**What we do:** Chunks overlap by 150 characters.
**Fix:** Increase `CHUNK_OVERLAP` or `TOP_K` a little.

### Chunks are too big or too small
- **Too big:** each chunk covers many topics, so search is less exact and you send more tokens to the LLM.
- **Too small:** a chunk does not have enough context to make sense on its own.

**Fix:** 500 to 1500 characters works for most documents. Start with 1000 and test with real questions.

### Words cut in half
**What we do:** We split long paragraphs on spaces, not in the middle of a word. Only one very long "word" (like a long URL) is ever cut.

---

## Embedding and storage problems

### Search results get worse after changing the embedding model
**Why:** Vectors from different models live in different "spaces". They cannot be compared.
**Fix:** Delete the `chroma_db` folder and ingest everything again.

### Duplicate chunks after ingesting the same file twice
**What we do:** Before storing a file, we delete all its old chunks (`replace_source()`). Chunk ids are also made from the file name and position, so they are the same every time.

### Old text still shows up after editing a file
**Why:** If the new file has fewer chunks, a simple "upsert" would leave the extra old chunks behind.
**What we do:** We delete by source first, so this cannot happen.

### Two files with the same name in different folders
**Why:** If we used only the file name, the second file would replace the first.
**What we do:** When ingesting a folder, the source name is the path inside that folder, like `hr/policy.md` and `it/policy.md`.

### Rate limits or timeouts from OpenAI
**What we do:** The OpenAI client retries up to 3 times and waits up to 60 seconds. We also send embeddings in batches of 100, which means far fewer requests.
**Fix:** If you still hit limits with many files, ingest in smaller groups, or ask OpenAI for a higher limit.

### One broken file stops everything
**What we do:** `ingest_folder()` catches the error for that file, logs it, and moves on. At the end it shows how many files worked and how many failed. The command exits with code 1 if any file failed, so scripts can notice.

---

## Retrieval and answer problems

### The LLM makes up an answer
**What we do:**
- The system prompt says to use only the context, and to say "I could not find this in the documents." if the answer is not there.
- `temperature=0` makes answers less creative.
- If no chunk passes `MIN_RELEVANCE`, we do not call the LLM at all.

### "I could not find this" but the answer is in the documents
**Why:** The score was below `MIN_RELEVANCE`, or the right chunk was not in the top `TOP_K`.
**Fix:**
1. Look at the log line "Found X chunks, Y above relevance". It shows how many chunks were thrown away.
2. Lower `MIN_RELEVANCE` (for example to `0.1`), or raise `TOP_K`.
3. Try asking with words that are used in the document.

### Wrong chunks are found
**Why:** Vector search is about meaning, so it can miss exact words like product codes or names.
**Fix:** For this kind of data, add keyword search (for example BM25) next to vector search. This is called **hybrid search**. We left it out to keep the code simple.

### Hard to know where the answer came from
**What we do:** Each chunk is numbered in the prompt. The LLM is told to cite `[1]`, `[2]`. `ask()` returns a matching list of sources with file name, page and score.

---

## Testing problems

### Tests would cost money and need a key
**What we do:** Tests use a fake embedder (it counts words) and a fake LLM. The real ChromaDB is used, but in a temporary folder. Tests are free, fast and work offline.

### The fake embedder is not very smart
It only counts words, so it can be confused by common words like "the" or "if". That is fine for testing the pipeline logic. To test answer quality, use the real models with a small set of known questions and answers.

---

## Ideas for later (not needed now)

These would help a bigger, real-world app. We left them out on purpose to keep things simple:

- A web API (for example FastAPI) on top of `RAGPipeline`.
- Hybrid search (keyword + vector).
- A re-ranking step to sort the found chunks better.
- Skipping files that have not changed (save a file hash in the metadata).
- Evaluation: a list of test questions with expected answers, run after each change.
