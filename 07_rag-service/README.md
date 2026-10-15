# rag-service

Question answering over internal documents. Staff upload policy docs, runbooks
etc., and ask questions in plain English. Answers come back with citations and
only use documents the user is allowed to see.

Built with LangGraph (single agent, fixed graph), OpenSearch hybrid search
(BM25 + kNN), Bedrock for embeddings and generation, and a cross encoder for
reranking. Ingestion runs on a small EC2 worker fleet that pulls from SQS.

```
upload:  client -> POST /documents -> S3 -> SQS -> EC2 ingest workers -> OpenSearch
                          |                              |
                          +----- DynamoDB doc status ----+   <- GET /documents/{doc_id}
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
    worker.py         SQS polling worker, runs on EC2 (and locally with `make worker`)
    events.py         unpacks S3 events from SQS message bodies
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
scripts/              local ingest, seeding, CLI, stuck docs
infra/template.yaml   CloudFormation: bucket, queue + DLQ, status table, worker ASG, alarms
Dockerfile            API image (ECS)
Dockerfile.worker     ingest worker image (EC2)
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

Or run the API, and the ingest worker in a second terminal if you want uploads to work.
It's the same worker code that runs on EC2, pointed at localstack.

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
| `processing` | a worker is on it (or it's waiting to be retried after an error) |
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

### Ingest (bucket, queue, status table, worker fleet)

All in `infra/template.yaml`. The worker runs as a Docker container on each
instance of an Auto Scaling group that scales on queue depth (1 to 5 instances
by default). Create the ECR repo `kb-rag-worker` once, then:

```bash
make push-worker                    # build Dockerfile.worker, push to ECR tagged with the git sha

make deploy-ingest ENV=dev \
  SUBNETS=subnet-aaa,subnet-bbb SG=sg-123 \
  OPENSEARCH_HOST=<domain endpoint> OPENSEARCH_ARN=<domain arn>
```

Deploying a new image tag creates a new launch template version and the ASG
replaces instances one at a time. Messages a stopped worker was holding come
back on the queue and get picked up by another worker.

Subnets need a route to S3, SQS, DynamoDB, Bedrock, ECR and OpenSearch (NAT or
VPC endpoints). The worker security group only needs outbound 443, and the
OpenSearch domain must allow it. No SSH, use SSM Session Manager.

### API

The API is built from the `Dockerfile` and deployed to the shared ECS cluster
through the platform pipeline. It needs the same env vars as `.env.example`
minus `AWS_ENDPOINT_URL`, with `OPENSEARCH_USE_IAM=true`. Attach the
`ApiAccessPolicyArn` stack output to the API task role (S3 put + status table).

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
- No ASG termination lifecycle hook. A worker killed on scale-in loses its
  current doc, which is retried by another worker (safe, just slower).
