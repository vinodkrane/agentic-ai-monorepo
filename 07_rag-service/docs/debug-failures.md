# Debugging failures

Symptom first, then where to look. All logs go to CloudWatch:
`/kb-rag/ingest-worker-<env>` for ingest (one log stream per EC2 instance id),
the ECS service log group for the API.

## Ingest

### Start with the status

```bash
curl -s "localhost:8000/documents/<doc_id>?user_id=<uploader>" | jq
# or straight from the table
aws dynamodb get-item --table-name kb-rag-doc-status-dev --key '{"doc_id": {"S": "<doc_id>"}}'
```

| status | look at |
|---|---|
| `queued` for more than a couple of minutes | no worker has picked it up. see "Stuck in queued" |
| `processing` for more than 20 min | see "Stuck in processing" |
| `failed` | `error` has the exception. see "Messages in the DLQ" |
| `skipped` | `error` says why. not a bug, usually a scanned pdf or an unsupported file |
| `completed` but questions don't find it | it's a retrieval problem, go to the query section |

`attempts` on the row is the SQS receive count of the last try.

Search all worker logs for a doc:

```bash
aws logs filter-log-events --log-group-name /kb-rag/ingest-worker-dev \
  --filter-pattern '"<doc_id>"' --query 'events[].message' --output text
```

### Stuck in queued

1. Check the object exists: `aws s3 ls s3://kb-rag-docs-dev/uploads/<doc_id>/`.
   Not there -> the S3 put failed after the row was written. The row should be
   `failed`, if it isn't the API died between the two calls. Ask the user to re-upload.
2. Check the message reached the queue (`ApproximateNumberOfMessagesVisible` on
   `kb-rag-ingest-<env>`). Queue empty and nothing in flight -> the S3
   notification isn't firing, check the prefix filter is `uploads/` and the queue
   policy allows the bucket.
3. Messages are piling up -> workers aren't consuming. Check the fleet:
   ```bash
   aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names kb-rag-ingest-worker-dev \
     --query 'AutoScalingGroups[0].Instances[].[InstanceId,LifecycleState,HealthStatus]'
   ```
   - no instances in service -> check ASG activity history (launch failures, subnet
     out of IPs, AMI parameter)
   - instances running but nothing in the log group -> the container never
     started. Connect with SSM and look:
     ```bash
     aws ssm start-session --target <instance-id>
     sudo docker ps -a
     sudo docker logs ingest-worker --tail 100
     sudo cat /var/log/cloud-init-output.log   # user data errors, ECR login / pull failures
     ```
     Usual causes: ECR pull denied (instance role / image tag doesn't exist),
     `INGEST_QUEUE_URL is not set`, no route to SQS (NAT / VPC endpoint missing).
4. Fleet is at max (5) and the queue is still deep -> just a big batch, it'll
   drain. Check `ApproximateNumberOfMessagesVisible` is going down. Don't raise
   `MaxWorkers` without checking Bedrock quotas first.

The `kb-rag-ingest-queue-stale-<env>` alarm fires when the oldest message is
over 30 minutes old, which usually means step 3.

### Stuck in processing

A worker took the message and then died or was terminated (scale-in, deploy,
OOM, instance failure) before it could write the result. The heartbeat stops
when the worker dies, so SQS makes the message visible again within 300s and
another worker retries it. So first wait 5 minutes and check `attempts` went up.

If it's still stuck:

```bash
python -m scripts.stuck_docs                 # list
python -m scripts.stuck_docs --mark-failed   # give the uploader a real status
```

Search the worker logs for the doc_id. Things to look for:
- log stops mid-doc with no error -> container was killed. `docker inspect
  ingest-worker` on the instance shows `OOMKilled: true` for out of memory. Very
  large docs on t3.medium can do this, bump `InstanceType`.
- `visibility heartbeat failed` warnings -> the worker couldn't extend the
  message, so another worker may have started on the same doc. Check the role
  has `sqs:ChangeMessageVisibility`. The second run is safe (delete-before-index),
  it just wastes time.
- a doc that legitimately takes more than 20 min shows here too. It isn't stuck,
  the status row only updates at the start and end.

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
message body (it has the doc_id in it), then search the worker logs for the doc_id.
Usual causes:

| error | cause | fix |
|---|---|---|
| ThrottlingException | Bedrock limit | wait, then redrive. lower `MaxWorkers` if it keeps happening |
| AuthorizationException (403) from OpenSearch | worker role missing es:ESHttp* or domain access policy doesn't include the worker role | fix IAM / domain policy |
| `indexing failed` + mapper_parsing_exception | embedding dimension doesn't match the index | EMBED_DIM / model mismatch, see architecture.md about new index versions |
| ConnectTimeout to OpenSearch | worker SG not allowed by the domain SG | add the worker SG to the domain SG ingress on 443 |
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

### Status update errors in worker logs

`AccessDeniedException` on `UpdateItem` -> worker role is missing the DynamoDB
statement, or `STATUS_TABLE` points at the wrong env's table. The doc will
retry and land in the DLQ, fix the role then redrive.

### Deploy rolled out but workers still run the old code

The ASG only replaces instances when the launch template version changes, which
happens when `WorkerImage` changes. Re-pushing the same tag does nothing. Always
deploy with a new tag (`make push-worker` tags with the git sha). Check which
image an instance is running with `sudo docker inspect ingest-worker --format '{{.Config.Image}}'`.

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
