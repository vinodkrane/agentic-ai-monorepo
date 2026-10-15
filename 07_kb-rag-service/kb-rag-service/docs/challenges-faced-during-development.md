# Challenges faced during development

Notes on things that cost us time, roughly in the order we hit them. Kept here
so the next person doesn't repeat them.

## 1. S3 test event broke the lambda on day one

When the bucket notification is first set up, S3 sends a `s3:TestEvent` message
with no `Records`. The handler assumed there would always be records, threw
a KeyError, and the message kept retrying until it hit the DLQ. The DLQ alarm
went off before a single real document was uploaded.

Fix: `events.py` skips the test event explicitly. There's a unit test for it.

## 2. Messages processed twice

Large PDFs took a few minutes to embed. The queue visibility timeout was still
the default 30 seconds, so the message became visible again while the first
lambda was still running, and a second lambda picked it up. We got duplicate
chunks in the index.

Fix: visibility timeout set to 6x the lambda timeout (AWS recommendation).
Also made ingestion idempotent: chunk ids are `<doc_id>-<index>` and we delete
by `doc_id` before indexing, so running the same file twice gives the same result.

## 3. Stale chunks after re-upload

Related to the above. Originally doc_id came from the S3 key, so re-uploading
to the same key overwrote chunks by id. Someone uploaded a shorter version of a
policy, the new chunks overwrote ids 0-11 but the old 12-19 stayed. Answers
mixed old and new policy.

First fix was `delete_doc` before `index_chunks`. When we added the status API
(see 16) every upload got its own doc_id, so a new version became a separate
doc. Now a new version is uploaded with `replaces=<old doc_id>` and the old
chunks are deleted only after the new version is fully indexed.

## 4. URL encoded keys

A file called `Expenses Policy 2026.pdf` came through as `Expenses+Policy+2026.pdf`
in the event and `get_object` returned NoSuchKey. `unquote_plus` on the key.

## 5. kNN with a post filter returned too few results

First version ran the kNN query and applied the group filter afterwards. For
users in small groups most of the top 20 nearest neighbours belonged to other
groups, so after filtering they'd get 2 or 3 results, sometimes none. Recall for
those users was terrible but looked fine in our tests because the test users
were in the big group.

Fix: moved the filter inside the `knn` clause (efficient filtering, needs the
faiss engine). Added `acl-*` rows to the golden set with users in small groups.

## 6. BM25 and vector scores can't be compared

We tried a weighted sum of BM25 score and cosine similarity. BM25 scores are
unbounded and vary per query, so the weight that worked for one question was
wrong for the next. Min-max normalising per query helped a bit but was fragile.
Switched to RRF which only uses ranks. Less to tune, k=60 worked out of the box.

## 7. Exact terms lost in pure vector search

Before adding BM25, questions like "what's the P1 ack time" returned P2 and P3
sections because they're semantically almost identical. BM25 gets the exact token.
This was the main reason for going hybrid.

## 8. PDF extraction quality

- Hyphenated line breaks ("exam-\nple") split words and hurt BM25. Fixed in `parser.clean`.
- Tables in PDFs come out as a jumble of numbers. Not fixed. Textract would help.
- Scanned PDFs return empty text. We log a warning and skip. Textract again.
- docx tables were silently dropped by `doc.paragraphs`. We now read tables too.

## 9. Tiny chunks polluting results

Page numbers, "Confidential" footers and headers became their own chunks and
matched everything with a high BM25 score for short queries. We drop chunks
under 30 characters.

## 10. Reranker on Lambda

We first tried running the query path on Lambda too. The cross encoder pulls in
torch, which put the package over the 250MB limit, and cold starts were several
seconds while the model loaded. Moved the query path to ECS where the model is
baked into the image and loaded once per worker. The ingest lambda doesn't need
torch so it stays small (`requirements-lambda.txt`).

## 11. Bedrock throttling during bulk ingest

Uploading a folder of ~200 docs at once spun up lots of lambdas and Titan started
returning ThrottlingException. Reserved concurrency of 5 on the ingest lambda
fixed it. The queue just drains slower, which is fine for an async path.

## 12. deepeval defaults to OpenAI

deepeval metrics call OpenAI unless you give them a model. We can't send internal
docs outside AWS, so `evals/judge.py` wraps Claude on Bedrock. The judge sometimes
returns JSON wrapped in prose, which deepeval mostly copes with, but one or two
faithfulness cases are flaky between runs. We run nightly and look at trends,
not single failures.

## 13. Measuring TTFT wrong

The first latency numbers looked great because we timed from the LLM call, not
from the request. Users were waiting for retrieval and rerank too. The latency
eval now adds retrieve + rerank + LLM ttft. The per-node timings are still
returned separately so we can see which part is slow.

## 14. Model repeating personal data from the docs

The runbook has a contact email and phone number. Even with "don't repeat
personal data" in the prompt, asking "how do I contact the vendor escalation
person" got the number back most of the time. Prompt rules aren't enough, so
`check_output` redacts with regex as a hard stop. The safety eval has probes for this.

## 15. Graph vs agent loop

We built a version where the LLM called a `search` tool and decided when to stop.
It sometimes searched 3-4 times for simple questions, doubling latency and cost,
and the traces were harder to read. The fixed graph gave the same or better
eval scores. Kept the fixed graph.

## 16. Nobody could tell if an upload had worked

Upload returned "queued" and that was it. Users re-uploaded the same file three
times because they couldn't see anything happening, and failed docs only showed
up as a DLQ alarm that the uploader never saw.

Added a DynamoDB status table and `GET /documents/{doc_id}`. Upload returns the
doc_id. Things we got wrong on the way:

- **Status row written after the S3 put.** The lambda sometimes got the event
  before the row existed, the conditional update failed and the doc looked
  `queued` forever while actually being indexed. Row now goes in first.
- **Marking `failed` on the first error.** Bedrock throttles are usually gone by
  the second try, so users saw `failed` and re-uploaded a doc that then completed
  anyway. Now `failed` is only set on the last attempt (`ApproximateReceiveCount`
  vs `MAX_RECEIVE_COUNT`, which has to match the queue's redrive policy).
- **Duplicate SQS delivery flipping `completed` back to `processing`.** All
  updates are conditional on the current status now.
- **Status endpoint leaked filenames.** First version returned the row to anyone
  with the doc_id. Now only the uploader and members of the doc's groups get it,
  everyone else gets 404.

## 17. Lambda vs EC2 workers for ingest

We seriously considered replacing the lambda with an EC2 worker fleet polling
SQS. For the docs we have (text PDFs, docx, markdown) Lambda finishes well
inside its limits, and with workers we'd have to build autoscaling on queue
depth, graceful shutdown, visibility timeout extension and patching ourselves.
Decided to stay on Lambda and move to ECS Fargate workers (not raw EC2) if we
add OCR or heavy parsing. The status table means that switch won't change the
API at all. Details in architecture.md.
