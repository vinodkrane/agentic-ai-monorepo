# StreamBox Support Agent — Observability Demo

A small AI agent that answers questions about a made-up video streaming service called **StreamBox**.

The agent itself is simple on purpose. This project is really about **how to watch, test and debug** an AI app:

| Area | Tool | What it answers |
|---|---|---|
| Tracing | LangSmith | What happened inside one request? How slow was it? How many tokens? How much did it cost? Where did it fail? |
| Evaluation | LangSmith | Are the answers good? Did my last change make them better or worse? |
| Regression tests | pytest | Does the code still work? Did an old bug come back? |
| Structured logging | Python `logging` (JSON) | What did the app do, step by step, for every request? |

---

## How the agent works

```
question
   │
   ▼
validate  ──(bad input)──▶ ValidationError
   │
   ▼
choose route
   ├── "direct"   (hello, thanks)          ──▶ LLM ──▶ answer
   └── "retrieve" (everything else)
            │
            ▼
      search help docs ──(nothing found)──▶ "Sorry, I could not find this..."
            │
            ▼
           LLM (with the docs as context) ──▶ answer + sources
```

- The help documents are in `data/docs/` (five short Markdown files).
- Search is a simple keyword match. No vector database, no cost.
- The LLM is OpenAI (`gpt-4o-mini` by default).

---

## Project layout

```
agentic-observability-demo/
├── app/
│   ├── agent.py          the agent: route, retrieve, call LLM, log, trace
│   ├── retriever.py      keyword search over data/docs
│   ├── llm.py            OpenAI client wrapped for LangSmith
│   ├── prompts.py        prompt versions v1 and v2
│   ├── validation.py     input checks
│   ├── logging_setup.py  JSON log formatter, request id
│   ├── config.py         settings from environment variables
│   └── cli.py            command line entry point
├── data/docs/            the help documents the agent searches
├── eval/
│   ├── datasets/         evaluation examples (JSON)
│   ├── evaluators.py     scoring functions
│   ├── create_datasets.py  upload datasets to LangSmith
│   ├── run_experiment.py   run an experiment in LangSmith
│   └── compare_runs.py     compare two experiments, flag drops
├── tests/                pytest tests
├── doc/                  the four learning guides
├── logs/                 app.log is written here
├── .env.example
├── pytest.ini
└── requirements.txt
```

---

## Setup (Windows)

You need **Python 3.10 or newer**.

Open PowerShell in the project folder:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

If PowerShell blocks the activate script, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

On macOS or Linux use `source .venv/bin/activate` and `cp .env.example .env`.

Now open `.env` and add your keys:

- `OPENAI_API_KEY` — from https://platform.openai.com/api-keys
- `LANGSMITH_API_KEY` — from https://smith.langchain.com → Settings → API Keys

If your LangSmith account is in the EU region, also set `LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`.

---

## Try it

**1. Run the tests (no API keys needed, free):**

```powershell
pytest
```

You should see something like `70 passed, 3 deselected`.

**2. Ask the agent a question:**

```powershell
python -m app.cli "How many days do I have to ask for a refund?"
```

The answer is printed. JSON logs are printed to the console and written to `logs\app.log`.

**3. See the trace:** open https://smith.langchain.com → Tracing projects → `streambox-agent`.

**4. Run an evaluation:**

```powershell
python -m eval.create_datasets
python -m eval.run_experiment --dataset rag --prompt-version v1
python -m eval.run_experiment --dataset rag --prompt-version v2
```

Then compare the two experiments in LangSmith, or locally:

```powershell
python -m eval.compare_runs eval\results\<v1 file>.json eval\results\<v2 file>.json
```

---

## Command cheat sheet

| What | Command |
|---|---|
| Ask a question | `python -m app.cli "your question"` |
| Run local tests | `pytest` |
| Run local tests, more detail | `pytest -v` |
| Run only regression tests | `pytest tests/test_regressions.py -v` |
| Run live OpenAI tests (costs a little) | `pytest -m live` |
| Upload eval datasets | `python -m eval.create_datasets` |
| Replace datasets after editing JSON | `python -m eval.create_datasets --recreate` |
| Run RAG experiment | `python -m eval.run_experiment --dataset rag` |
| Run agent experiment | `python -m eval.run_experiment --dataset agent` |
| Add LLM-as-judge | `python -m eval.run_experiment --dataset rag --judge` |
| Compare two experiments | `python -m eval.compare_runs old.json new.json` |
| Show only errors from the log | `Get-Content logs\app.log \| ConvertFrom-Json \| Where-Object level -eq "ERROR"` |

---

## Learning guides

Read these in order:

1. [doc/01-langsmith-tracing.md](doc/01-langsmith-tracing.md)
2. [doc/02-langsmith-evaluation-and-metrics.md](doc/02-langsmith-evaluation-and-metrics.md)
3. [doc/03-pytest-regression-testing.md](doc/03-pytest-regression-testing.md)
4. [doc/04-structured-logging.md](doc/04-structured-logging.md)

---

## How the four parts fit together

Think of one bad answer reported by a user:

1. **Logs** — you search `logs/app.log` for errors or slow requests and find the `request_id` and `trace_id`.
2. **Tracing** — you open that trace in LangSmith and see exactly which documents were found and what the LLM was sent.
3. **Evaluation** — you add the question to an evaluation dataset, change the prompt, and run an experiment to check the fix helps and nothing else got worse.
4. **pytest** — you add a regression test so the bug can never come back without a test failing.

---

## Safety notes

- Never commit `.env`. It is in `.gitignore`.
- Logs never contain API keys. The log formatter masks anything that looks like a key.
- User questions are **not** written to logs unless you set `LOG_QUESTIONS=true`.
- LangSmith traces **do** contain the questions and answers. Treat your LangSmith project as private data.
