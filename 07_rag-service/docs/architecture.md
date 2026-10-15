# Architecture

## Overview

Two separate paths that only share the OpenSearch index and the embedding model.
Ingest also writes a status row per document to DynamoDB so clients can poll it.

```
INGEST (async)

  client ──POST /documents──> API ──1. create row (queued)──> DynamoDB doc status
         <── 202 {doc_id} ──   │                                  ^       ^
                               │ 2. put_object                    │       │ GET /documents/{doc_id}
                               v                                  │       │ (API reads it)
                     S3  uploads/<doc_id>/<file>                  │
                               │ ObjectCreated                    │ processing / completed /
                               v                                  │ failed / skipped / replaced
                     SQS ingest queue ──(3 fails)──> DLQ ──> alarm│
                               │ long poll                        │
                               v                                  │
              EC2 ingest workers (ASG, 1-5, scales on queue depth)┘
               parse -> chunk -> embed (Titan v2) -> bulk index
                               │
                               v
                     OpenSearch  kb-chunks-v1
                               ^
QUERY (sync)                   │ bm25 + knn (both filtered by group)
                               │
  client ──POST /query──> API ─┴─> LangGraph agent
                      check_input -> retrieve -> fuse + acl -> rerank
                      -> generate (Claude on Bedrock, streamed) -> check_output
```

## Components

| Component | What it does | Notes |
|---|---|---|
| API (FastAPI on ECS) | upload, doc status, `/query` | Stateless, 2 uvicorn workers per task |
| S3 bucket | Raw uploaded files | Versioned, KMS. ACL groups and doc_id stored as object metadata |
| SQS + DLQ | Buffers ingest work | visibility 300s (extended by worker heartbeat), maxReceiveCount 3, alarm when DLQ > 0 |
| DynamoDB `kb-rag-doc-status` | One row per doc_id: status, groups, uploader, chunk_count, error | On demand billing, PITR on |
| Ingest workers (EC2 ASG) | Poll SQS, parse, chunk, embed, index | t3.medium, Docker container per instance, 1-5 instances |
| OpenSearch | BM25 text index + HNSW vectors in the same doc | faiss engine, inner product, 1024 dims |
| Bedrock Titan embed v2 | Embeddings | Normalised vectors |
| Cross encoder | Rerank top 20 | ms-marco-MiniLM-L-6-v2, runs on CPU in the API container |
| Bedrock Claude | Answer generation, also the eval judge | temperature 0 |

## Why a single agent

We started with the idea of a router agent + retrieval agent + answer agent.
In practice every question goes through the same steps, and the extra LLM hops
added latency and made failures harder to trace. A fixed LangGraph graph with
two branches (blocked, nothing found) covers what we need and every node can be
tested on its own. If we later need query rewriting or multi hop questions, it
goes in as one extra node before `retrieve`, not a new agent.

## Ingest workers on EC2

Ingest started on Lambda. We moved it to an EC2 worker fleet polling SQS because:

- **No 15 minute ceiling.** Big PDFs (hundreds of pages, each chunk embedded
  separately) were getting close to the limit, and OCR / Textract
  post-processing is on the roadmap which will make it worse.
- **Heavier parsing libraries** (layout models, `unstructured`) fit on an instance
  without fighting package size limits.
- **Predictable concurrency against Bedrock.** One worker processes one doc at a
  time, so max instances = max concurrent embedders. Easy to reason about when
  Titan throttles.
- **Steady volume.** Docs come in all day from the sync jobs, so an always-on
  small instance costs about the same and has no cold starts.

What we had to build ourselves because Lambda did it for us before:

| concern | how it's handled |
|---|---|
| scaling on queue depth | step scaling: +1 instance when > 10 visible for 2 min, +2 when > 60. -1 after 15 min with nothing visible **and nothing in flight** |
| a big doc outliving the visibility timeout | heartbeat thread in `worker.py` extends visibility by 300s every 60s while working |
| deleting messages | worker deletes on success / skip, leaves it on error |
| retry backoff | on error the worker sets visibility to `60s * attempt` so retries spread out |
| graceful shutdown | SIGTERM -> finish current doc -> exit. container runs with `--stop-timeout 300` |
| worker crashes | `docker run --restart always` |
| instance dies mid doc | message becomes visible again, another worker redoes it. ingest is idempotent |
| deploys | new image tag -> new launch template version -> ASG rolling update, 1 at a time |
| patching | instances use the latest AL2023 AMI at launch. re-deploy the stack monthly to roll them |
| access | no SSH, SSM Session Manager only. IMDSv2 required |
| logs | docker `awslogs` driver -> `/kb-rag/ingest-worker-<env>` |

We considered ECS Fargate for the workers (no instances to patch, same pattern
as the API). EC2 was chosen so we can move to bigger or GPU instance types for
OCR / local embedding models later without changing the setup. If that never
happens, Fargate is the obvious simplification - the worker code doesn't change,
only the infra.

Things that are deliberately simple:

- **One message at a time per worker.** No threads, no batch handling. Throughput
  comes from instance count. Easier to debug, and Bedrock is the bottleneck anyway.
- **Step scaling, not target tracking on backlog per instance.** Good enough for
  our volume.
- **No termination lifecycle hook.** If scale-in kills a worker mid doc, the doc
  is retried elsewhere. Scale-in only happens when nothing is in flight, so this
  is rare.

## Document status

Upload returns a `doc_id` (uuid) straight away with `202 Accepted`. The client
polls `GET /documents/{doc_id}`. We didn't want users guessing whether a doc was
still indexing or had silently failed.

```
queued -> processing -> completed -> replaced
             |   ^
             v   |  (DLQ redrive)
           failed
queued/processing -> skipped
```

Decisions:

- **DynamoDB, not OpenSearch**, for status. It's a key lookup that needs
  conditional writes. OpenSearch is eventually consistent and a failed doc has
  no chunks to hang a status on.
- **doc_id is generated by the API**, not derived from the S3 key, and passed to
  the worker in S3 object metadata (`doc-id`). The S3 key is `uploads/<doc_id>/<file>`.
- **Status row is written before the S3 put.** A worker can get the event
  within a second. If the put fails the API marks the row `failed`.
- **Every update is conditional** (see `app/status.py`). SQS is at least once, so
  a duplicate message must not move `completed` back to `processing`. The worker
  drops the message if `start_processing` returns False.
- **`failed` is only set on the last attempt** (`ApproximateReceiveCount >= 3`).
  Before that the doc stays `processing` while SQS retries. After the last
  attempt the message goes to the DLQ, and a redrive is allowed to move `failed`
  back to `processing`.
- **`skipped`** is for things retrying won't fix. Those messages are deleted, not
  retried, so they never reach the DLQ.
- **New versions** are uploaded with `replaces=<old doc_id>`. The old chunks are
  only deleted after the new version is indexed, so there's no window where the
  doc can't be found.
- **Visibility**: the uploader and anyone in the doc's groups can see the status.
  Everyone else gets 404, not 403, so we don't confirm the doc exists. Uploaders
  can only assign groups they are a member of.

A doc stuck in `processing` (worker killed and the message hasn't come back
yet, or something worse) is found with `scripts/stuck_docs.py`, see debug-failures.md.

## Why hybrid search

Policy docs are full of exact terms: "P1", "45p per mile", "February window".
Pure vector search kept missing these, BM25 kept missing paraphrased questions
("can I claim a beer" vs "alcohol cannot be claimed"). Running both and fusing
with RRF fixed most of both kinds of miss. RRF uses rank only, so we don't
need to normalise BM25 and cosine scores against each other.

## Access control

Every chunk carries `allowed_groups` copied from the S3 metadata at ingest time.
ACL is enforced in two places:

1. Inside the OpenSearch queries (`terms` filter on BM25, efficient `filter`
   inside the knn clause).
2. Again in `acl.py` after fusion. This should never drop anything. If it does,
   it logs an error because something upstream is wrong.

A document with no groups is not indexed at all (status `skipped`).

## Index schema

```
chunk_id        keyword   "<doc_id>-0003"
doc_id          keyword   uuid from the API, same as the status table key
source          keyword   original filename
page            integer
chunk_index     integer
allowed_groups  keyword   ["all-staff"]
text            text      english analyzer
embedding       knn_vector 1024, hnsw, faiss, innerproduct, m=16, ef_construction=128
```

If the schema or embedding model changes, create `kb-chunks-v2`, re-ingest and
switch `INDEX_NAME`. Don't edit the live index in place.

## Security

- Nothing leaves AWS. Embeddings, generation and the eval judge all go through Bedrock.
- PII is redacted from the question before it reaches the embedding model or the LLM,
  and again from the answer before it's returned.
- Workers and API use IAM to sign OpenSearch requests, no basic auth.
- The API role can only `PutObject` under `uploads/` and read/write the status
  table. The worker role can read `uploads/`, receive/delete/extend messages on
  the ingest queue and update status rows, not create them.
- Worker instances run in private subnets, outbound 443 only, IMDSv2, encrypted
  EBS, no SSH.
