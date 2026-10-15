# kb-rag-service

Question answering over internal documents. Staff upload policy docs, runbooks
etc., and ask questions in plain English. Answers come back with citations and
only use documents the user is allowed to see.

Built with LangGraph (single agent, fixed graph), OpenSearch hybrid search
(BM25 + kNN), Bedrock for embeddings and generation, and a cross encoder for
reranking.

```
upload:  client -> POST /documents -> S3 -> SQS -> ingest lambda -> OpenSearch
                          |                            |
                          +---- DynamoDB doc status ---+   <- GET /documents/{doc_id}
query:   client -> POST /query -> LangGraph agent -> OpenSearch + Bedrock -> answer
```

More detail in [docs/architecture.md](docs/architecture.md) and [docs/flow.md](docs/flow.md).

## Repo layout

```
app/
  api.py              FastAPI app, /documents, /documents/{doc_id}, /query
  config.py           all settings, read from env
  aws.py              boto3 + opensearch clients
  embeddings.py       titan v2 embeddings (used by ingest and query)
  users.py            user -> groups lookup (static json for now)
  status.py           doc ingest status in DynamoDB (queued/processing/completed/...)
  ingest/
    handler.py        lambda entry point
    events.py         unpacks S3 events from SQS messages
    parser.py         pdf / docx / txt / md -> text
    chunker.py        recursive splitter, adds ACL groups to every chunk
    indexer.py        index mapping, bulk index, delete old chunks
  query/
    graph.py          the LangGraph agent
    retriever.py      bm25 and knn queries
    fusion.py         reciprocal rank fusion
    acl.py            post retrieval ACL re-check
    reranker.py       cross encoder rerank
    generator.py      bedrock call, streams to get TTFT / TPS
    guardrails.py     PII + toxicity checks
    prompts.py
evals/                golden set, regression, deepeval, safety, latency
tests/                unit tests, AWS faked with moto
scripts/              local ingest, seeding, CLI, local queue poller, stuck docs
infra/template.yaml   SAM template for bucket, queue, DLQ, status table, lambda
docs/
```

## Running locally

You need Docker, Python 3.12 and AWS credentials with Bedrock access in
eu-west-2 (Titan embed v2 and Claude enabled in the console). S3, SQS and
DynamoDB run in localstack, OpenSearch runs in Docker. `make setup` uses the
aws cli.

```bash
python -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env          # set AWS_PROFILE if you use one

make up                        # opensearch + localstack
make setup                     # bucket, queue + dlq, status table, s3 notification
make seed                      # load data/sample_docs into opensearch
```

Ask something straight from the CLI:

```bash
python -m scripts.ask alice "how many days of leave can I carry over?"
python -m scripts.ask bob "how fast do I ack a P1?"   # bob isn't in platform-eng, should get no answer
```

Or run the API (and the queue poller in a second terminal if you want uploads to work):

```bash
make api
make worker

# upload - returns a doc_id straight away (202), indexing happens in the background
curl -s -F "file=@data/sample_docs/expenses-policy.md" -F "groups=all-staff" -F "user_id=alice" \
  localhost:8000/documents
# {"doc_id": "3f2c9a...", "status": "queued"}

# poll status
curl -s "localhost:8000/documents/3f2c9a...?user_id=alice" | jq
# {"doc_id": "3f2c9a...", "status": "completed", "filename": "expenses-policy.md", "chunk_count": 4, ...}

# new version of the same doc: pass the old doc_id, old chunks are removed once the new one is indexed
curl -s -F "file=@expenses-policy-v2.md" -F "groups=all-staff" -F "user_id=alice" -F "replaces=3f2c9a..." \
  localhost:8000/documents

curl -s localhost:8000/query -H 'content-type: application/json' \
  -d '{"user_id": "bob", "question": "what is the hotel limit in London?"}' | jq
```

Example query response:

```json
{
  "answer": "The limit is 150 pounds per night in London, including breakfast [1].",
  "citations": [{"n": 1, "source": "expenses-policy.md", "page": 1, "chunk_id": "..."}],
  "blocked": false,
  "timings_ms": {"retrieve": 120, "rerank": 85, "ttft": 610, "generate": 1400, "tps": 58.3, "total": 1650}
}
```

### Document status values

| status | meaning |
|---|---|
| `queued` | in S3, waiting on the queue |
| `processing` | lambda is working on it (or retrying after an error) |
| `completed` | searchable. `chunk_count` is set |
| `failed` | gave up after 3 attempts, `error` says why. message is in the DLQ |
| `skipped` | retrying won't help: unsupported type, no text (scanned PDF), no groups |
| `replaced` | a newer upload replaced it, `replaced_by` has the new doc_id |

Status is visible to the uploader and anyone in the doc's groups, everyone else gets 404.

## Tests and evals

```bash
make test             # unit tests, AWS faked with moto, runs in CI on every PR
make eval-retrieval   # recall@k / precision@k + ACL leak checks, needs seeded index
make eval-llm         # deepeval faithfulness, relevancy, context metrics, PII, toxicity
make eval-latency     # TTFT, tokens/sec, p50/p95 against budget
```

See [docs/evals.md](docs/evals.md) for what each one checks and the thresholds.

## Deploying

The ingest lambda, bucket, queues and status table are in `infra/template.yaml`:

```bash
make lambda-zip
sam deploy --template-file infra/template.yaml --stack-name kb-rag-ingest-dev \
  --parameter-overrides Env=dev OpenSearchHost=<endpoint> OpenSearchDomainArn=<arn> \
  --capabilities CAPABILITY_IAM
```

The API is built from the `Dockerfile` and deployed to the shared ECS cluster
through the platform pipeline. It needs the same env vars as `.env.example`
minus `AWS_ENDPOINT_URL`, with `OPENSEARCH_USE_IAM=true`. Attach the
`ApiAccessPolicyArn` stack output to the API task role (S3 put + status table).

### Why Lambda and not EC2/ECS workers for ingest

Ingest is parse + Bedrock calls + bulk index, which fits comfortably inside
Lambda's 15 minutes and needs no torch. If we add OCR, Textract post-processing
or layout models, move it to ECS Fargate workers polling the same queue. The
status table and API don't change. See [architecture.md](docs/architecture.md).

## Docs

- [architecture.md](docs/architecture.md) - components and why we picked them
- [flow.md](docs/flow.md) - step by step for ingest and query
- [evals.md](docs/evals.md) - golden set, metrics, thresholds
- [challenges-faced-during-development.md](docs/challenges-faced-during-development.md)
- [debug-failures.md](docs/debug-failures.md) - runbook for when things break

## Known gaps

- Scanned PDFs produce no text. Textract would fix this, not done yet.
- User groups come from `data/users.json`. Needs wiring to the identity service.
- No conversation memory, every question is standalone.
- `user_id` is passed in the request. In live it should come from the auth token.
- No `DELETE /documents/{doc_id}` yet.
- Toxicity check on the hot path is a word list. Bedrock Guardrails is the likely replacement.
