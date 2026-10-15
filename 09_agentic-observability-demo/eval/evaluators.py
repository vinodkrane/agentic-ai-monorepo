"""Evaluators for LangSmith experiments.

Each evaluator gets the agent output and the expected output from the dataset,
and returns {"key": <metric name>, "score": <0..1>, "comment": <why>}.

Most of them are plain Python (free, fast, testable with pytest).
The LLM judge is optional because it costs money.
"""
import json

from app.agent import NO_ANSWER

REFUSAL_PHRASES = ("don't know", "do not know", "could not find", NO_ANSWER.lower())


def _phrase_found(phrase, text):
    """A phrase can list alternatives separated by '|', e.g. "two | 2"."""
    options = [option.strip().lower() for option in phrase.split("|")]
    return any(option and option in text for option in options)


def _fraction_found(phrases, text):
    if not phrases:
        return 1.0, []
    text = text.lower()
    missing = [phrase for phrase in phrases if not _phrase_found(phrase, text)]
    return (len(phrases) - len(missing)) / len(phrases), missing


def is_refusal(answer):
    answer = answer.lower()
    return any(phrase in answer for phrase in REFUSAL_PHRASES)


# ---------- RAG evaluators ----------

def correctness(outputs, reference_outputs):
    """Does the answer contain the key facts we expect?"""
    score, missing = _fraction_found(reference_outputs.get("must_include", []), outputs.get("answer", ""))
    comment = "all facts found" if not missing else f"missing: {missing}"
    return {"key": "correctness", "score": score, "comment": comment}


def context_recall(outputs, reference_outputs):
    """Did the retrieved documents contain the facts needed to answer?"""
    context = "\n".join(outputs.get("contexts", []))
    score, missing = _fraction_found(reference_outputs.get("must_include", []), context)
    comment = "context has all facts" if not missing else f"context missing: {missing}"
    return {"key": "context_recall", "score": score, "comment": comment}


def retrieval_hit(outputs, reference_outputs):
    """Was the expected document among the retrieved ones?"""
    expected = reference_outputs.get("expected_source")
    sources = outputs.get("sources", [])
    hit = expected in sources
    return {"key": "retrieval_hit", "score": 1.0 if hit else 0.0, "comment": f"expected {expected}, got {sources}"}


# ---------- Agent evaluators ----------

def route_match(outputs, reference_outputs):
    """Did the agent pick the route we expected (direct or retrieve)?"""
    expected = reference_outputs.get("expected_route")
    actual = outputs.get("route")
    return {"key": "route_match", "score": 1.0 if expected == actual else 0.0, "comment": f"expected {expected}, got {actual}"}


def refusal_check(outputs, reference_outputs):
    """The agent should say 'I don't know' for out-of-scope questions, and only then."""
    should_refuse = reference_outputs.get("expected_refusal", False)
    refused = is_refusal(outputs.get("answer", ""))
    ok = refused == should_refuse
    return {"key": "refusal_check", "score": 1.0 if ok else 0.0,
            "comment": f"should refuse={should_refuse}, refused={refused}"}


# ---------- Optional LLM-as-judge ----------

JUDGE_PROMPT = """You grade answers from a customer support bot.
Question: {question}
Reference answer: {reference}
Bot answer: {answer}

Is the bot answer correct and relevant to the question, when compared with the reference?
Reply with JSON only: {{"score": <number from 0 to 1>, "reason": "<one sentence>"}}"""


def make_llm_judge(api_key, model="gpt-4o-mini"):
    """Returns an evaluator that asks an LLM to grade the answer. Costs a little money per example."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    def llm_judge(inputs, outputs, reference_outputs):
        prompt = JUDGE_PROMPT.format(
            question=inputs.get("question", ""),
            reference=reference_outputs.get("answer", ""),
            answer=outputs.get("answer", ""),
        )
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(response.choices[0].message.content)
        return {"key": "llm_judge", "score": float(data.get("score", 0)), "comment": data.get("reason", "")}

    return llm_judge


RAG_EVALUATORS = [correctness, context_recall, retrieval_hit]
AGENT_EVALUATORS = [route_match, refusal_check, correctness]
