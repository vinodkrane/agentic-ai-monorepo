# 3. Automated Regression Testing with pytest

## What is a regression test?

A **regression** is when something that used to work breaks again.

A **regression test** is an automated check that runs every time you change the code. If an old bug comes back, the test fails and tells you.

## pytest tests vs LangSmith evaluation

They are different and you need both.

| | pytest | LangSmith evaluation |
|---|---|---|
| Checks | Does the **code** work? | Are the **AI answers** good? |
| Result | Pass or fail | A score from 0 to 1 |
| Speed | Under 1 second | Seconds to minutes |
| Cost | Free | Costs API money |
| When | Every change, on every machine, in CI | When you change prompts, models or search |

## How we test without paying for the LLM

Most tests use a **fake LLM** instead of OpenAI. It is in `tests/conftest.py`:

```python
class FakeLLM:
    def __init__(self, answer="This is a fake answer.", error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    def complete(self, system_prompt, user_prompt):
        self.calls.append({"system": system_prompt, "user": user_prompt})
        if self.error:
            raise self.error
        return LLMResult(text=self.answer, model="fake-model", input_tokens=120, output_tokens=30)
```

It has the same `complete()` method as the real `OpenAIChatModel`, so the agent cannot tell the difference.

The fake LLM is useful in two ways:

- It **remembers** each call. A test can check what prompt the agent sent, or that the LLM was **not** called.
- It can **raise an error** on purpose, so we can test error handling.

`conftest.py` also sets `LANGSMITH_TRACING=false`, so tests never send data to LangSmith.

The agent gets the LLM passed in (`SupportAgent(llm=..., retriever=...)`), which is what makes this swap easy.

## The test files

| File | What it tests |
|---|---|
| `test_validation.py` | Empty, too long, and non-text questions are rejected. |
| `test_retriever.py` | Documents load. The right document is ranked first. Unrelated questions find nothing. |
| `test_agent.py` | Response structure, routing, error handling, and what the agent logs. |
| `test_logging.py` | JSON format, request id, exception details, secrets are masked. |
| `test_evaluators.py` | Evaluator scores, dataset files, experiment comparison. |
| `test_regressions.py` | One test for each bug we fixed. |
| `test_live_llm.py` | Real OpenAI calls. Skipped by default. |

### Example: response structure

```python
def test_response_has_expected_structure(agent):
    response = agent.ask("How many days do I have to ask for a refund?")
    assert response.route == "retrieve"
    assert response.sources[0] == "refund-policy"
    assert response.input_tokens == 120
```

### Example: error handling

```python
def test_llm_failure_becomes_agent_error_and_logs_error(retriever, json_logs):
    broken_llm = FakeLLM(error=LLMError("OpenAI call failed: timeout"))
    agent = SupportAgent(llm=broken_llm, retriever=retriever)

    with pytest.raises(AgentError, match="not available"):
        agent.ask("How do I reset my password?")

    errors = [line for line in json_logs() if line["level"] == "ERROR"]
    assert errors[0]["exception"]["type"] == "LLMError"
```

This one test checks three things: the error is turned into a friendly `AgentError`, exactly one ERROR log line is written, and the log line has the exception details.

## Regression tests for known bugs

`tests/test_regressions.py` has one test per bug. Each test name starts with `test_bug_<number>_` and the docstring tells the story:

```python
def test_bug_004_empty_context_made_llm_invent_answers(agent, fake_llm):
    """With no matching documents we still called the LLM, and it made up an answer from general knowledge."""
    response = agent.ask("Who won the football last night?")
    assert response.answer == NO_ANSWER
    assert fake_llm.calls == []
```

The bugs covered:

1. A question with only spaces reached the LLM.
2. Punctuation (`refund?`) stopped the keyword match.
3. Repeated words gave documents too high a score.
4. With no documents found, the LLM made up answers.
5. The request id stayed set after a request ended.
6. `Hello!` was not seen as small talk.
7. An API key inside an error message was written to the logs.

**The rule:** when you fix a bug, first write a test that fails because of the bug. Then fix the code. Now the test passes and the bug can never come back quietly.

## Live tests (optional)

`tests/test_live_llm.py` calls the real OpenAI API. These tests are marked with `@pytest.mark.live`.

`pytest.ini` skips them by default:

```ini
addopts = -m "not live"
```

Run them on purpose when you want to check the real integration:

```powershell
pytest -m live
```

They need `OPENAI_API_KEY` in `.env`. If it is missing, they are skipped, not failed.

Live tests check simple, stable things only (the answer contains "14", the source is `refund-policy`). Quality checks belong in LangSmith evaluation, not in pytest.

## Commands

Activate your virtual environment first.

| What | Command |
|---|---|
| Run all local tests | `pytest` |
| Show each test name | `pytest -v` |
| Run one file | `pytest tests/test_agent.py` |
| Run one test | `pytest tests/test_agent.py::test_choose_route` |
| Run tests whose name contains a word | `pytest -k refusal` |
| Stop at the first failure | `pytest -x` |
| Show print output and logs | `pytest -s` |
| Run live tests only | `pytest -m live` |

## Reading the results

A good run:

```
......................................................................   [100%]
70 passed, 3 deselected in 0.40s
```

- Each `.` is a passing test.
- `3 deselected` are the live tests that were skipped on purpose.

A failing run:

```
F.....................................................................
FAILED tests/test_retriever.py::test_best_document_is_ranked_first[How much does the Premium plan cost?-subscription-plans]
    assert 'downloads' == 'subscription-plans'
```

- `F` means a test failed.
- The `FAILED` line shows which test and which input.
- The `assert` line shows what we got (`downloads`) and what we expected (`subscription-plans`).

Other letters: `s` means skipped, `E` means the test setup itself crashed.

## When to run the tests

- Before every commit: `pytest`
- In CI on every pull request: `pytest`
- Before a release, or after upgrading the OpenAI library: `pytest -m live`

## Summary

- pytest checks the **code**. LangSmith evaluation checks **AI quality**.
- A fake LLM keeps tests free, fast and repeatable.
- Every fixed bug gets a regression test.
- Real API tests are marked `live` and only run when you ask.
