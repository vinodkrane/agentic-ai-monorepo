# 2. LangSmith Evaluation and Experiments

## What is evaluation?

Tracing shows what happened in **one** request. Evaluation checks **how good** the agent is over **many** questions.

You give the agent a list of questions where you already know the right answer. Then you score each answer. The average score tells you the quality.

Why do we need it? Because AI answers change when you change the prompt, the model, or the search. A change that fixes one question can break three others. Evaluation shows you this before your users do.

## Three words to know

| Word | Meaning | In this project |
|---|---|---|
| **Dataset** | A list of examples. Each example has an input and the expected output. | `eval/datasets/*.json` |
| **Evaluator** | A function that gives a score to one answer. | `eval/evaluators.py` |
| **Experiment** | One run of the agent over a whole dataset, with all the scores. | `python -m eval.run_experiment` |

## The datasets

We have two datasets.

### RAG dataset — `eval/datasets/rag_dataset.json`

Checks that the agent finds the right document and gives the right facts.

```json
{
  "inputs": {"question": "How many days do I have to ask for a refund?"},
  "outputs": {
    "answer": "You can ask for a refund within 14 days of your first payment.",
    "must_include": ["14 days | 14-day | fourteen days"],
    "expected_source": "refund-policy"
  }
}
```

- `must_include` — facts the answer must contain. Use `|` to allow different ways of writing the same fact.
- `expected_source` — the document that should be found.
- `answer` — a reference answer. The optional LLM judge uses it.

### Agent dataset — `eval/datasets/agent_dataset.json`

Checks the agent's **decisions**, not only its text.

```json
{
  "inputs": {"question": "What is the capital of France?"},
  "outputs": {
    "expected_route": "retrieve",
    "expected_refusal": true,
    "must_include": []
  }
}
```

- `expected_route` — should the agent search the docs (`retrieve`) or just reply (`direct`)?
- `expected_refusal` — should the agent say "I don't know"? For questions that are not about StreamBox, it should.

## The evaluators

All evaluators are in `eval/evaluators.py`. Each one returns a score from 0 to 1.

| Evaluator | Dataset | What it checks |
|---|---|---|
| `correctness` | both | Does the answer contain the `must_include` facts? |
| `context_recall` | RAG | Did the **retrieved documents** contain the facts? |
| `retrieval_hit` | RAG | Was `expected_source` in the retrieved documents? |
| `route_match` | agent | Did the agent pick the expected route? |
| `refusal_check` | agent | Did the agent say "I don't know" only when it should? |
| `llm_judge` | both (optional) | An LLM grades correctness and relevance against the reference answer. |

An evaluator is just a normal Python function:

```python
def retrieval_hit(outputs, reference_outputs):
    expected = reference_outputs.get("expected_source")
    hit = expected in outputs.get("sources", [])
    return {"key": "retrieval_hit", "score": 1.0 if hit else 0.0, "comment": f"expected {expected}"}
```

- `outputs` is what our agent returned.
- `reference_outputs` is the expected output from the dataset.
- LangSmith passes these in by name.

### Why separate `context_recall` and `correctness`?

They tell you **where** a problem is:

| context_recall | correctness | Meaning |
|---|---|---|
| high | high | All good |
| low | low | **Search** problem. The right document was not found. |
| high | low | **LLM / prompt** problem. The facts were there, but the answer missed them. |

### Why are most evaluators simple string checks?

They are free, fast, never change their mind, and you can test them with pytest. The LLM judge is useful for open answers, but it costs money and can be a bit random, so it is optional (`--judge`).

## How an experiment works

```
LangSmith dataset ──▶ for each example:
                         agent.ask(question)      (traced)
                         run every evaluator      (scores saved)
                    ──▶ experiment with scores per example and averages
```

The `target` function in `eval/run_experiment.py` connects the agent to LangSmith:

```python
def target(inputs):
    response = agent.ask(inputs["question"])
    return {"answer": response.answer, "route": response.route,
            "sources": response.sources, "contexts": response.contexts}
```

Then:

```python
Client().evaluate(
    target,
    data="streambox-rag-qa",
    evaluators=[correctness, context_recall, retrieval_hit],
    experiment_prefix="rag-v1",
    metadata={"prompt_version": "v1", "model": "gpt-4o-mini"},
)
```

Each example in the experiment links to its full trace, so you can click a low score and see exactly what happened.

## Step by step

### Step 1 — Upload the datasets

```powershell
python -m eval.create_datasets
```

This reads every JSON file in `eval/datasets/` and creates the datasets in LangSmith. If a dataset already exists, it is skipped.

You can see them in LangSmith under **Datasets & Experiments**.

### Step 2 — Run an experiment

```powershell
python -m eval.run_experiment --dataset rag --prompt-version v1
```

At the end you see a short summary, for example:

```
Experiment: rag-v1-1a2b3c4d
  context_recall  1.00
  correctness     0.88
  retrieval_hit   1.00
Summary saved to eval\results\rag-v1-1a2b3c4d.json
```

(Your numbers may be different. LLM answers change a little between runs.)

### Step 3 — Make a change and run again

The project has two prompt versions in `app/prompts.py`. `v2` is stricter: it tells the model to answer only from the context and to keep exact numbers.

```powershell
python -m eval.run_experiment --dataset rag --prompt-version v2
python -m eval.run_experiment --dataset agent --prompt-version v1
python -m eval.run_experiment --dataset agent --prompt-version v2
```

The agent dataset includes "Does StreamBox have a free trial?". The docs do not say. `v1` may make up an answer. `v2` should say it does not know. Watch `refusal_check` change.

### Step 4 — Compare the experiments

**In LangSmith (best view):**

1. Open **Datasets & Experiments** and click the dataset.
2. You see all experiments with their average scores.
3. Tick two experiments and click **Compare**.
4. LangSmith shows each question side by side, with the scores in red or green where they changed.

**On your computer:**

```powershell
python -m eval.compare_runs eval\results\rag-v1-xxxx.json eval\results\rag-v2-yyyy.json
```

Example output:

```
metric             old   new  change  status
context_recall    1.00  1.00    0.00  SAME
correctness       0.88  1.00    0.12  BETTER
retrieval_hit     1.00  1.00    0.00  SAME

No metric got worse.
```

If any metric drops by more than 0.05, it says `WORSE` and the command exits with code 1. You can use this in a CI pipeline to block changes that make quality worse.

## Managing examples

To add a new example:

1. Open the JSON file in `eval/datasets/`.
2. Copy an example and change the question and expected output.
3. Upload again with `--recreate`:
   ```powershell
   python -m eval.create_datasets --recreate
   ```

`--recreate` deletes the old dataset and uploads a new one. Old experiments for that dataset are deleted too. If you want to keep old experiments, add examples in the LangSmith website instead (open the dataset → **+ Example**). LangSmith keeps a version history of every dataset.

A good habit: when a user reports a bad answer, add that question to the dataset. Your dataset grows with real problems.

## Using the optional LLM judge

```powershell
python -m eval.run_experiment --dataset rag --judge
```

This adds `llm_judge`. An LLM reads the question, the reference answer, and the agent's answer, and gives a score from 0 to 1 with a reason. You can read the reason in LangSmith by clicking the score.

## Testing the evaluation code with pytest

The evaluators are normal functions, so we test them locally for free. See `tests/test_evaluators.py`. It checks:

- each evaluator gives the right score,
- the dataset files are valid,
- every `expected_source` really exists in `data/docs/`,
- the retriever finds the expected document for every RAG example (no LLM needed),
- `compare_scores` flags drops correctly.

This means a broken evaluator or a typo in a dataset is caught before you spend money on an experiment.

## Summary

- A **dataset** is questions with known answers.
- An **evaluator** scores one answer.
- An **experiment** runs the agent over a dataset and saves all scores.
- Change one thing (prompt, model, `TOP_K`), run a new experiment, and **compare**.
- Use cheap code evaluators first. Add the LLM judge when you need it.
