# 1. LangSmith Tracing

## What is tracing?

When you ask the agent a question, many small things happen: the question is checked, documents are searched, the LLM is called, and an answer comes back.

A **trace** is a record of all those steps for **one request**. It is like a receipt that shows every item, how long each took, and what it cost.

Each step inside a trace is called a **run**. Runs can have child runs, so a trace looks like a tree.

## Why is it useful?

Without tracing, an AI app is a black box. You only see the question and the answer.

With tracing you can answer questions like:

- Why was this answer wrong? (Which documents did it find? What prompt did the LLM get?)
- Why was this request slow? (Was it the search or the LLM?)
- How many tokens did we use, and how much did it cost?
- Where exactly did it fail, and with what error?

## How LangSmith tracing works in this project

We only need two things from the `langsmith` package.

**1. `@traceable` — trace our own functions**

```python
# app/agent.py
@traceable(name="support_agent", run_type="chain")
def _run(self, question, request_id):
    ...
```

```python
# app/retriever.py
@traceable(name="retrieve_documents", run_type="retriever")
def search(self, query):
    ...
```

Every time these functions run, LangSmith records the inputs, outputs, start time, end time and any error.

**2. `wrap_openai` — trace every LLM call**

```python
# app/llm.py
self._client = wrap_openai(OpenAI(api_key=api_key, ...))
```

This one line makes LangSmith record each OpenAI call with the full prompt, the answer, the **token usage**, and the **cost**.

That is all. LangSmith sends the data in the background, so your app does not slow down.

## The flow of one request

When you run:

```powershell
python -m app.cli "How many days do I have to ask for a refund?"
```

LangSmith shows a tree like this:

```
support_agent                 (chain)      820 ms
├── retrieve_documents        (retriever)    1 ms
└── ChatOpenAI                (llm)        810 ms   412 tokens   $0.0001
```

- `support_agent` is the whole request. Its input is the question; its output is the full response.
- `retrieve_documents` shows which documents were found and their scores.
- `ChatOpenAI` shows the exact messages sent to the model and its reply.

For a greeting like `hello`, there is no `retrieve_documents` step — the agent chose the `direct` route.
For a question with no matching documents, there is no `ChatOpenAI` step — the agent answered "Sorry, I could not find this..." without calling the LLM.

So the shape of the trace tells you what decision the agent made.

## Extra information we attach to each trace

In `SupportAgent.ask()` we send **metadata** and **tags** with the trace:

```python
self._run(
    question,
    request_id,
    langsmith_extra={
        "metadata": {"request_id": request_id, "prompt_version": self.prompt_version},
        "tags": ["support-agent", f"prompt-{self.prompt_version}"],
    },
)
```

- `request_id` is the same id that is in our JSON logs. You can jump from a log line to the trace.
- `prompt_version` lets you filter traces by prompt, e.g. only `v2`.

We also save the LangSmith `trace_id` in the final log line, so you can go the other way too.

## How to configure it

In your `.env` file:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_your-key
LANGSMITH_PROJECT=streambox-agent
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

- `LANGSMITH_TRACING=true` turns tracing on. Set it to `false` to turn it off. No code change is needed.
- `LANGSMITH_PROJECT` is the folder in LangSmith where traces go. It is created for you.
- If your account is in the EU region, use `LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`.

The tests turn tracing off on purpose (see `tests/conftest.py`), so running `pytest` never sends anything to LangSmith.

## How to view traces

1. Run a few questions:
   ```powershell
   python -m app.cli "How much does the Premium plan cost?"
   python -m app.cli "hello"
   python -m app.cli "What is the capital of France?"
   ```
2. Go to https://smith.langchain.com
3. Click **Tracing projects** (or **Projects**) and open `streambox-agent`.
4. You see one row per request. Click a row to open the trace tree.

## How to inspect latency

- The project table has a **Latency** column. Sort by it to find slow requests.
- Inside a trace, each run shows its own time. If `ChatOpenAI` takes 800 ms and the whole request takes 820 ms, the LLM is the slow part.
- The project's **Monitor** (or Dashboard) tab shows latency charts over time, such as P50 (typical) and P99 (worst cases).

## How to inspect token usage and cost

- Open the `ChatOpenAI` run. You see **input tokens** (the prompt) and **output tokens** (the answer).
- LangSmith knows the price of common OpenAI models, so it shows the **cost** next to the tokens.
- The project table shows **total tokens** and **total cost** per trace.
- The Monitor tab shows cost per day.

A simple tip: the input tokens are mostly the documents we send as context. If cost goes up after a change, check if `TOP_K` was increased.

Our JSON logs also contain `input_tokens` and `output_tokens`, so you can add them up without LangSmith if you need to.

## How to inspect errors

Try a broken request. For example, put a wrong key in `.env`:

```
OPENAI_API_KEY=sk-wrong-key-123456789
```

and run:

```powershell
python -m app.cli "How do I reset my password?"
```

In LangSmith:

- The trace is marked in **red** with an error status.
- Open it. The failing run (`ChatOpenAI`) shows the error message and stack trace.
- Parent runs (`support_agent`) are also marked as failed, so you can see how the error moved up.
- In the project table, use the filter **Status = Error** to see only failed requests.

Validation errors (for example an empty question) also appear as errors on the `support_agent` run.

## Tracing vs logging

| | LangSmith traces | JSON logs |
|---|---|---|
| Best for | Looking inside AI steps: prompts, answers, documents, tokens, cost | Following what the app did, alerts, searching many requests |
| Contains user text? | Yes (questions and answers) | No, by default |
| Where | LangSmith website | `logs/app.log` and the console |
| Works without internet? | No | Yes |

Use both. Logs tell you **that** something went wrong and give you the `request_id`. The trace shows you **why**.

## Summary

- `@traceable` traces your own functions.
- `wrap_openai` traces LLM calls with tokens and cost.
- Turn tracing on and off with `LANGSMITH_TRACING`.
- Open the project in LangSmith to see latency, tokens, cost and errors for every request.
