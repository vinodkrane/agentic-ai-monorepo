# 4. Structured Logging with Python `logging`

## What is structured logging?

A normal log line is plain text:

```
2026-10-15 14:03:21 INFO Documents retrieved: 2 docs in 0.4ms
```

People can read it, but computers find it hard to search. How do you find "all requests slower than 2 seconds"?

A **structured** log line is data. In this project every line is one JSON object:

```json
{"timestamp": "2026-10-15T13:03:21.611+00:00", "level": "INFO", "logger": "app.agent",
 "message": "Documents retrieved", "request_id": "33eb81043f4e",
 "operation": "agent.retrieve", "status": "success", "doc_count": 2,
 "sources": ["refund-policy", "subscription-plans"], "duration_ms": 0.4}
```

Now you can filter by any field: `level`, `request_id`, `status`, `duration_ms` and so on.

## The fields we log

| Field | Example | Why |
|---|---|---|
| `timestamp` | `2026-10-15T13:03:21.611+00:00` | When it happened (UTC) |
| `level` | `INFO`, `WARNING`, `ERROR` | How serious it is |
| `logger` | `app.agent` | Which part of the code |
| `message` | `Documents retrieved` | Short human text |
| `request_id` | `33eb81043f4e` | Groups all lines from one request |
| `operation` | `agent.retrieve` | Which step |
| `status` | `started`, `success`, `rejected`, `failed`, `empty` | Did the step work? |
| `duration_ms` | `812.3` | How long it took |
| `route`, `sources`, `doc_count` | | What the agent decided |
| `model`, `input_tokens`, `output_tokens` | | LLM usage |
| `trace_id` | | Link to the LangSmith trace |
| `exception` | `{type, message, traceback}` | Only on errors |

## Log levels

| Level | When we use it | Example in this project |
|---|---|---|
| `INFO` | Normal steps | Request received, documents retrieved, LLM call finished |
| `WARNING` | Something unusual, but we handled it | Question rejected, no documents matched |
| `ERROR` | Something failed | LLM call failed, unexpected error |

Set the minimum level with `LOG_LEVEL` in `.env`. With `LOG_LEVEL=WARNING` you only see warnings and errors.

## How it works

All the code is in `app/logging_setup.py`. It is about 100 lines.

### 1. A JSON formatter

Python's `logging` module lets you choose how each line looks. Our `JsonFormatter` turns a log record into JSON:

```python
class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "timestamp": ...,
            "level": record.levelname,
            "logger": record.name,
            "message": mask_secrets(record.getMessage()),
            "request_id": request_id_var.get(),
        }
        # + any fields passed with extra={...}
        # + exception details if there is one
        return json.dumps(entry)
```

### 2. Extra fields with `extra={...}`

This is standard Python logging. Any field you pass in `extra` goes into the JSON:

```python
logger.info(
    "LLM call finished",
    extra={"operation": "agent.llm", "status": "success", "model": result.model,
           "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
           "duration_ms": _ms_since(start)},
)
```

### 3. Request id with `contextvars`

We do not want to pass `request_id` to every function. Instead, `SupportAgent.ask()` puts it in a **context variable** at the start of the request:

```python
request_id = request_id or new_request_id()
token = request_id_var.set(request_id)
try:
    ...
finally:
    request_id_var.reset(token)
```

The formatter reads it for every line. So every log line written during that request has the same `request_id`, without any extra work. A `ContextVar` is also safe when many requests run at the same time (threads or async).

The `finally` part resets it, so the id does not leak into the next request. (This was bug #5 — see `tests/test_regressions.py`.)

### 4. Errors with `exc_info=True`

```python
logger.error("LLM call failed", exc_info=True, extra={...})
```

`exc_info=True` adds the exception to the log line:

```json
"exception": {"type": "LLMError", "message": "OpenAI call failed: timeout", "traceback": "Traceback (most recent call last): ..."}
```

### 5. Where the logs go

`setup_logging()` sends logs to two places:

- **stderr** (the console). We use stderr so the answer printed on stdout stays clean.
- **`logs/app.log`**, one JSON object per line (this is called "JSON Lines").

## The flow of one request in the logs

```powershell
python -m app.cli "How do I reset my password?"
```

Writes five lines, all with the same `request_id`:

| # | operation | status | useful fields |
|---|---|---|---|
| 1 | `agent.ask` | `started` | `question_chars`, `prompt_version` |
| 2 | `agent.route` | `success` | `route` |
| 3 | `agent.retrieve` | `success` | `doc_count`, `sources`, `duration_ms` |
| 4 | `agent.llm` | `success` | `model`, `input_tokens`, `output_tokens`, `duration_ms` |
| 5 | `agent.ask` | `success` | total `duration_ms`, `trace_id` |

If the LLM fails, line 4 is missing and line 5 becomes an `ERROR` with `status: failed` and an `exception`.

## Searching the logs

### PowerShell (Windows)

```powershell
# All errors
Get-Content logs\app.log | ConvertFrom-Json | Where-Object level -eq "ERROR"

# Everything for one request
Get-Content logs\app.log | ConvertFrom-Json | Where-Object request_id -eq "33eb81043f4e"

# Slow requests (over 2 seconds)
Get-Content logs\app.log | ConvertFrom-Json |
  Where-Object { $_.operation -eq "agent.ask" -and $_.status -eq "success" -and $_.duration_ms -gt 2000 }

# Total tokens used
Get-Content logs\app.log | ConvertFrom-Json | Where-Object operation -eq "agent.llm" |
  Measure-Object -Property input_tokens, output_tokens -Sum
```

### jq (macOS, Linux, or Windows with jq installed)

```bash
jq 'select(.level == "ERROR")' logs/app.log
jq 'select(.request_id == "33eb81043f4e")' logs/app.log
jq -s 'map(select(.operation == "agent.retrieve")) | group_by(.status) | map({status: .[0].status, count: length})' logs/app.log
```

### Python

```python
import json
with open("logs/app.log", encoding="utf-8") as f:
    lines = [json.loads(line) for line in f]
errors = [l for l in lines if l["level"] == "ERROR"]
```

In production you would send these lines to a log platform (for example CloudWatch, Datadog, ELK or Grafana Loki). They all understand JSON, so no change is needed.

## Keeping secrets and user data out of logs

**API keys.** The formatter masks anything that looks like an OpenAI key (`sk-...`) or a LangSmith key (`lsv2_...`), and any field named `api_key`, `password`, `secret` or `authorization`:

```json
"message": "Incorrect API key provided: [REDACTED]"
```

This matters because some libraries put the key inside their error messages. (This was bug #7.)

**User questions.** By default we only log the **length** of the question (`question_chars`), not the text. Questions can contain names, emails or other personal data. If you need the text while debugging, set `LOG_QUESTIONS=true` in `.env`, and set it back to `false` after.

## Logs vs LangSmith traces

| | JSON logs | LangSmith traces |
|---|---|---|
| Main question | What did the app do? Is it healthy? | What happened inside the AI steps? |
| Contains | Steps, status, timings, token counts, errors | Full prompts, answers, documents, tokens, cost |
| User text | No (by default) | Yes |
| Covers | Everything, including non-AI code | AI steps you trace |
| Needs internet | No | Yes |
| Good for alerts | Yes ("more than 5 errors a minute") | Partly |
| Kept for | As long as you like | Depends on your LangSmith plan |

**How to use them together:**

1. Logs show a problem: an `ERROR`, or a request with a large `duration_ms`.
2. Copy its `trace_id` (from the `agent.ask` success line) or its `request_id`.
3. In LangSmith, open the trace (or filter by metadata `request_id`).
4. See the exact prompt, documents and model reply.

## Summary

- Each log line is one JSON object, so it is easy to search.
- `request_id` connects all lines of one request. `trace_id` connects a log to its LangSmith trace.
- Use `INFO` for normal steps, `WARNING` for handled problems, `ERROR` for failures.
- Every step logs `operation`, `status` and `duration_ms`.
- Keys are masked. User text is off by default.
