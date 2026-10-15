# Request flows

## 1. Upload / ingest

1. Client sends `POST /documents` (multipart) with `file`, `groups` (comma separated),
   `user_id` and optionally `replaces=<old doc_id>`.
2. API checks:
   - extension is pdf, docx, txt or md, size under 20MB, not empty -> else 400/413
   - at least one group, and the uploader is a member of every group -> else 400/403
   - if `replaces` is set, that doc exists and the uploader can see it -> else 404
3. API generates `doc_id` (uuid4 hex) and writes the status row to DynamoDB with
   status `queued`. This happens **before** the S3 put so the row is always there
   when a worker looks for it.
4. API writes the file to `s3://kb-rag-docs-<env>/uploads/<doc_id>/<filename>` with
   metadata `doc-id`, `groups`, `original-name`, `replaces`. If the put fails the
   row is marked `failed` and the client gets a 500.
5. API returns `202 {"doc_id": "...", "status": "queued"}`. The user doesn't wait for indexing.
6. S3 sends an `ObjectCreated` event to the ingest SQS queue (prefix filter `uploads/`).
7. An ingest worker (`app/ingest/worker.py`, one container per EC2 instance) is
   long polling the queue and receives **one** message, asking for
   `ApproximateReceiveCount`. The message is now invisible to other workers for 300s.
8. The worker starts a heartbeat thread that pushes the visibility timeout out by
   another 300s every 60s, so a big doc is never handed to a second worker.
9. `events.py` unpacks the S3 event from the message body (skips the S3 test
   event, url-decodes the key). For the object, `worker.process_object`:
   - gets the object, reads `doc-id` from metadata. No doc-id -> log and drop
     (something wrote to the bucket without going through the API).
   - `status.start_processing` -> `processing`. If the doc is already
     `completed`/`skipped`/`replaced` this returns False and the message is dropped
     (duplicate delivery).
   - parse -> chunk -> embed -> delete any partial chunks for this doc_id -> bulk index
   - `status.mark_completed(chunk_count)`
   - if `replaces` was set: delete the old doc's chunks, mark the old row `replaced`
10. Heartbeat stops. Then:
    - success or `skipped` (no groups, unsupported type, no text) -> worker deletes the message
    - any other error -> message is **not** deleted. The worker sets its visibility
      to `RETRY_DELAY_SECONDS * attempt` (60s, 120s) so it comes back after a short
      backoff. Status stays `processing`. On the 3rd attempt the doc is marked
      `failed` with the error, and SQS moves the message to the DLQ.
11. The worker goes back to polling.

If the worker or instance dies at any point in 9, nothing is deleted, the heartbeat
stops, and the message is visible again within 300s for another worker. The retry
deletes any partial chunks first, so the end result is the same.

On SIGTERM (deploy, scale-in, `docker stop`) the worker finishes the message it
is on and exits. It doesn't take a new one.

Typical time from upload to `completed` is under a minute for a normal sized doc,
plus up to 20s for the long poll if the worker was idle, plus ~2 min if the ASG
has to add an instance during a burst.

### Worker scaling

```
visible messages > 10 for 2 min       -> +1 instance (+2 if > 60)    max 5
visible + in flight == 0 for 15 min   -> -1 instance                  min 1
```

### Status check

```
GET /documents/{doc_id}?user_id=alice

200 {"doc_id": "...", "status": "completed", "filename": "expenses-policy.md",
     "groups": ["all-staff"], "chunk_count": 4, "error": null,
     "replaces": null, "replaced_by": null,
     "created_at": "2026-10-14T21:10:03+00:00", "updated_at": "2026-10-14T21:10:41+00:00"}
```

404 if the doc doesn't exist **or** the user isn't the uploader and isn't in any
of its groups. Clients should poll every few seconds and stop on `completed`,
`failed`, `skipped` or `replaced`.

| status | final? | what the client should do |
|---|---|---|
| queued | no | keep polling |
| processing | no | keep polling |
| completed | yes | doc is searchable |
| failed | yes* | show `error`. may come back to processing if the DLQ is redriven |
| skipped | yes | show `error` (e.g. scanned pdf), user needs to upload a different file |
| replaced | yes | follow `replaced_by` |

## 2. Query

```
POST /query {user_id, question}
   │
   ├─ users.get_groups(user_id)            no groups -> 403
   │
   v
check_input ── toxic? ──────────────────────────────> BLOCKED_ANSWER
   │ redact PII from question
   v
retrieve        bm25_search(q, groups)  top 20
                knn_search(embed(q), groups)  top 20
   v
fuse_and_acl    rrf([bm25, knn], k=60)
                acl_filter(groups)  (re-check)
   v
rerank          cross encoder over top 20 -> top 5
   │
   ├─ no docs left? ───────────────────────────────> NO_ANSWER (no LLM call)
   v
generate        Claude on Bedrock, streamed
                records ttft_ms, gen_ms, tps
   v
check_output    toxic? -> BLOCKED_ANSWER
                PII? -> redact
   v
response {answer, citations, blocked, timings_ms}
```

### State that moves through the graph

| key | set by | used by |
|---|---|---|
| question, user_id, groups | API | everything |
| clean_question | check_input | retrieve, rerank, generate |
| bm25_hits, knn_hits | retrieve | fuse_and_acl |
| candidates | fuse_and_acl | rerank |
| docs | rerank | generate, citations, evals |
| answer, citations | generate / no_answer | check_output, API |
| blocked | check_input / check_output | API |
| timings | retrieve, rerank, generate | API, latency eval |

### Generation prompt

System prompt in `app/query/prompts.py`. Chunks are numbered `[1]..[5]` with
their source and page so the model can cite them. The model is told to say it
couldn't find the answer rather than guess, and to never repeat personal data.
