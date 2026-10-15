# Debugging failures

Symptom first, then where to look. All logs go to CloudWatch:
`/aws/lambda/kb-rag-ingest-<env>` for ingest, the ECS service log group for the API.

## Ingest

### Start with the status

```bash
curl -s "localhost:8000/documents/<doc_id>?user_id=<uploader>" | jq
# or straight from the table
aws dynamodb get-item --table-name kb-rag-doc-status-dev --key '{"doc_id": {"S": "<doc_id>"}}'
```

| status | look at |
|---|---|
| `queued` for more than a couple of minutes | the lambda isn't getting the event. see "Stuck in queued" |
| `processing` for more than 20 min | see "Stuck in processing" |
| `failed` | `error` has the exception. see "Messages in the DLQ" |
| `skipped` | `error` says why. not a bug, usually a scanned pdf or an unsupported file |
| `completed` but questions don't find it | it's a retrieval problem, go to the query section |

`attempts` on the row is the SQS receive count of the last try.

### Stuck in queued

1. Check the object exists: `aws s3 ls s3://kb-rag-docs-dev/uploads/<doc_id>/`.
   Not there -> the S3 put failed after the row was written. The row should be
   `failed`, if it isn't the API died between the two calls. Ask the user to re-upload.
2. Check the queue has messages / the lambda is being invoked (CloudWatch
   `Invocations` metric). Nothing -> the S3 notification isn't firing, check the
   prefix filter is `uploads/` and the queue policy allows the bucket.
3. Lambda throttled -> reserved concurrency is 5, a big batch upload just takes
   a while. Check `ApproximateNumberOfMessagesVisible` is going down.

### Stuck in processing

The lambda was killed (timeout, out of memory) after `start_processing` and
before it could write the result. SQS will redeliver after the visibility
timeout, so first wait for that (90 min with our settings). If it's still
stuck:

```bash
python -m scripts.stuck_docs                 # list
python -m scripts.stuck_docs --mark-failed   # give the uploader a real status
```

Search the lambda logs for the doc_id. `Task timed out` or `Runtime exited`
with memory errors -> the doc is too big for the lambda. Short term: bump
memory. If this keeps happening, it's the signal to move ingest to ECS workers
(see architecture.md).

### Status `completed` but questions don't find it

1. Check the chunks exist:
   ```bash
   curl -s "localhost:9200/kb-chunks-v1/_search?q=doc_id:<doc_id>&size=0" | jq .hits.total
   ```
2. Check `groups` on the status row include a group the asking user is in.
3. Then it's retrieval, go to the query section.

### Messages in the DLQ

Alarm `kb-rag-ingest-dlq-not-empty-<env>` fired.

```bash
aws sqs receive-message --queue-url <dlq-url> --max-number-of-messages 5
```

The doc's status row will be `failed` with the error. Get the key from the
message body (it has the doc_id in it), then search lambda logs for the doc_id.
Usual causes:

| error | cause | fix |
|---|---|---|
| ThrottlingException | Bedrock limit | wait, then redrive. lower reserved concurrency if it keeps happening |
| AuthorizationException (403) from OpenSearch | lambda role missing es:ESHttp* or domain access policy | fix IAM / domain policy |
| `indexing failed` + mapper_parsing_exception | embedding dimension doesn't match the index | EMBED_DIM / model mismatch, see architecture.md about new index versions |
| Task timed out after 900s | very large doc | split the doc, or bump timeout and visibility timeout together |
| PdfReadError | corrupt or encrypted PDF | ask the owner for an unlocked copy |

After fixing, redrive from the DLQ in the console (SQS -> DLQ -> Start DLQ redrive).
The redriven message moves the status from `failed` back to `processing` and
on to `completed`. A redrive sends the message back as a new message, so the
receive count starts again and it gets the full 3 attempts.

### Same document showing up twice in answers

Every upload gets a new doc_id. Uploading a new version **without**
`replaces=<old doc_id>` leaves both versions searchable. Find the old one
(the uploader will have its doc_id, or search the index by `source`) and
re-upload with `replaces`, or delete its chunks:

```bash
curl -s -XPOST "localhost:9200/kb-chunks-v1/_delete_by_query" -H 'content-type: application/json' \
  -d '{"query": {"term": {"doc_id": "<old doc_id>"}}}'
```

### Status update errors in lambda logs

`AccessDeniedException` on `UpdateItem` -> lambda role is missing the DynamoDB
statement, or `STATUS_TABLE` points at the wrong env's table. The doc will
retry and land in the DLQ, fix the role then redrive.

## Query

### Wrong or "couldn't find" answer when the doc is there

Run it locally against the same index and look at each stage:

```python
from app.query.graph import build_graph
from app.users import get_groups

s = build_graph().invoke({"question": "...", "user_id": "bob", "groups": get_groups("bob"), "timings": {}})
for name in ["bm25_hits", "knn_hits", "candidates", "docs"]:
    print(name, [(h["source"], h["chunk_id"]) for h in s.get(name, [])][:10])
```

Then:

- **Not in bm25_hits or knn_hits** -> retrieval. Check the user's groups match the
  doc's `allowed_groups`. Check the chunk text actually contains the answer (bad
  PDF extraction is common).
- **In hits but not in candidates** -> ACL re-check dropped it. Look for
  `ACL re-check dropped chunk` errors. This means the OpenSearch filter is broken.
- **In candidates but not in docs** -> reranker pushed it out of the top 5. Try
  `TOP_K=8` to confirm, then add the question to the golden set.
- **In docs but answer is still wrong** -> generation. Check the prompt, check
  whether the chunk cut the answer in half (chunk boundary), try a bigger overlap.

### ACL re-check errors in logs

`ACL re-check dropped chunk <id> - retrieval filter missed it` should never
appear. Treat it as a security bug. Check recent changes to `retriever.py` and
that the `filter` is still inside the `knn` clause.

### Slow responses

Look at `timings_ms` in the response or the `query ... total_ms` log line.

| slow part | likely cause |
|---|---|
| retrieve | OpenSearch under load, or the query embedding call to Bedrock is slow |
| rerank | CPU starved ECS task. check CPU utilisation, rerank only does 20 pairs |
| ttft | Bedrock latency, or a very long context (check chunk sizes) |
| generate with low tps | Bedrock side, check the Bedrock dashboard for the model |

First request after a deploy is slow because the reranker loads. It's baked in
the image so it's only the load time, not a download.

### Answer has [EMAIL] / [UK_PHONE] in it

That's `check_output` redacting something. Working as intended. If it's a false
positive (e.g. a reference number matching the card regex), tighten the pattern
in `guardrails.py` and add a unit test.

### 403 "user has no access to any documents"

The user isn't in `data/users.json` (or has no groups). Add them, redeploy.

## Evals

### Retrieval regression failing on a PR

The test prints `misses=[...]`. Run those questions with the snippet above on
`main` and on your branch and compare `docs`. Usual culprits: changed chunk size,
changed analyzer, changed RRF k.

### deepeval flaky

Judge output varies a bit. Re-run once. If the same case fails twice, it's real.
Use `deepeval test run evals/test_deepeval.py -v` to see the judge's reasoning.

### Latency eval over budget

Check you're running it in eu-west-2, not from a laptop. Then compare the
individual timings against the last nightly run to find which stage moved.
