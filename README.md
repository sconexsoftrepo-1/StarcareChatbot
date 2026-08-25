# Starcare Support Chatbot — RAG Backend

A FastAPI backend that answers "how do I use Starcare" questions **only**
from the Caregiver and Admin manuals, respecting the user's role. Runs on
Azure OpenAI (Microsoft Foundry), no SQL database, no separate vector
database server.

## Why no SQL database

Two things were candidates for a database, and neither needs one:

1. **Chat sessions** — one temporary chat per user, so an in-memory dict
   keyed by `user_id` with a TTL (`SESSION_TTL_MINUTES`, default 30) is
   enough. See `app/sessions.py`. If the server restarts, active sessions
   are lost — acceptable for a "temporary" chat.
2. **The manuals** — instead of Postgres+pgvector, this uses **Chroma**, a
   vector store that's just a local folder (`./chroma_data`). Nothing to
   run separately, `pip install` is all it takes.

If you later want chat history to survive a restart, or persistent support
tickets, SQLite is enough at this scale — it's a small addition, not a
redesign.

## Role model: caregiver or admin, nothing shared

Every chunk in `app/data/caregiver_chunks.json` and `app/data/admin_chunks.json`
is tagged `role: "caregiver"` or `role: "admin"` — there is no `"shared"`
role. Content both roles need (e.g. the sign-in/role-access flow) exists as
two independent chunks, one in each file, rather than one chunk both roles
draw from. Retrieval filters on an exact role match
(`where={"role": role}` in `app/rag_service.py`) — a caregiver query can
never retrieve an admin-only chunk, full stop.

## How the RAG pipeline works

1. Both manuals were pre-chunked **by hand, by section** (not auto-split) —
   13 caregiver chunks, 27 admin chunks. Each chunk keeps the manual's real
   section name, module, page number, and role tag, so e.g. "Overdue
   Section" stays one coherent chunk instead of being cut mid-workflow. A
   few chunks are hand-written **flows** that stitch several screens
   together end-to-end (e.g. the full Overdue → Missed Medication →
   Administered path) for "walk me through the process" style questions.
2. `scripts/ingest_manuals.py` embeds each chunk (Azure OpenAI embeddings)
   and upserts it into a local Chroma collection. It's idempotent — chunk
   IDs are fixed, so re-running it just updates the same rows.
3. On each chat message:
   - the question is embedded, **and** — if there's conversation history —
     also combined with the previous turn and embedded again; both
     retrievals run and results are merged, keeping the better-scoring hit
     per chunk. This is what lets follow-ups like *"what if it's overdue?"*
     work, without letting an unrelated prior question pollute retrieval
     when the user switches topics entirely (see `retrieve_combined` in
     `app/rag_service.py`)
   - the top `TOP_K` chunks are retrieved, filtered to the requester's exact
     role
   - any chunk below `RAG_SIMILARITY_THRESHOLD` is dropped
   - if nothing survives, the fixed "not enough information" message is
     returned and **the LLM is never called** — no chance to hallucinate
   - otherwise the LLM answers **using only that context**, with a system
     prompt that forbids inventing buttons/workflows/permissions, forbids
     medical advice, and returns structured JSON
     (`answer`, `can_answer`, `confidence`, `follow_up_questions`)

## Follow-up question suggestions

When the bot can answer, it also returns up to 2 suggested follow-up
questions in `follow_ups`. These are grounded twice over:

1. The LLM is only shown the same context chunks used for the answer (never
   the full manual) and told to suggest only what's answerable from them.
2. Each suggestion is independently re-run through retrieval before being
   returned — if it doesn't actually surface real manual content, it's
   silently dropped. This is a code-level guarantee, not just a prompt
   instruction.

When the bot **can't** answer, `follow_ups` instead returns two fixed
actions: a ready-to-send support email draft (`type: "draft_email"`,
template-built in `app/email_draft.py`, no LLM call — deterministic, no
hallucination risk in an email that goes to a real inbox) and an
`"end_chat"` action the frontend can wire to `POST /api/v1/chat/reset`.

## Handling Azure OpenAI's rate limits

Azure enforces a hard Requests-Per-Minute / Tokens-Per-Minute quota per
deployment. Firing a burst of concurrent requests at it just gets most of
them rejected with `429`s. `app/rate_limiter.py` paces outbound calls to
stay under the configured quota instead:

- `AZURE_CHAT_RPM` (default 50) and `AZURE_EMBEDDING_RPM` (default 300) —
  set these to match your actual Foundry deployment quota (Foundry portal →
  your project → Management/Operate → Quota).
- If a request would have to queue longer than `MAX_QUEUE_WAIT_SECONDS`
  (default 20) to get a slot, it fails fast with a clean `503` instead of
  holding the connection open for minutes.
- A real `429` from Azure itself (e.g. quota genuinely exhausted) is also
  caught and returned as a clean `503` rather than a raw `500`.

If `gpt-5-mini` (or another reasoning-tier deployment) rejects a custom
`temperature`, set `LLM_SEND_TEMPERATURE=false` in `.env` — no code change
needed.

## Role handling

`role` is currently passed in the request body (`caregiver` or `admin`).
**TODO (marked in `app/models.py`)**: in production, don't trust this from
the frontend — resolve it server-side from the real Starcare auth/JWT and
overwrite whatever the client sent before it reaches the chat logic.

## Run locally

```bash
cd starcare-rag
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, and the two
# deployment names to match your Foundry project

python scripts/ingest_manuals.py      # builds ./chroma_data from the manuals
uvicorn app.main:app --reload --port 8000
```

Swagger docs: http://localhost:8000/docs

## Try it

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","role":"caregiver","message":"Why can'\''t I administer this medication?"}'
```

Follow-up in the same temporary session:
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","role":"caregiver","message":"What if it is overdue?"}'
```

Should a caregiver ask something admin-only:
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","role":"caregiver","message":"How do I approve a medication variance report?"}'
```
→ returns `can_answer: false`, because no caregiver-tagged chunk covers
Admin-only MVR approval.

Reset a user's temporary session:
```bash
curl -X POST http://localhost:8000/api/v1/chat/reset -d '{"user_id":"u1"}' -H "Content-Type: application/json"
```

Log an escalation (optional, writes to a local SQLite file):
```bash
curl -X POST http://localhost:8000/api/v1/support/escalate \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","role":"caregiver","issue":"HTTP 504 when saving Monitoring"}'
```

## Load testing

```bash
python scripts/load_test.py --url http://localhost:8000 --concurrency 200
python scripts/load_test.py --url http://localhost:8000 --concurrency 500 --waves 3
```

Fires that many requests as a single burst, then reports success rate and
p50/p95/p99 latency. Watch the `Error breakdown` line — `503`s mean the rate
limiter (or Azure itself) is genuinely at capacity, which is a quota
question, not a bug.

## Concurrency

- All I/O (LLM calls, embeddings, Chroma queries) runs through async FastAPI
  endpoints — nothing blocks the event loop.
- The Azure OpenAI clients are created **once at import time** and reused
  for every request.
- `MAX_CONCURRENT_LLM_CALLS` caps how many Azure calls are in flight at once
  on top of the RPM pacing above.

## API keys

`AZURE_OPENAI_API_KEY` only ever lives in `.env` / real environment
variables on the server — never sent to or read by the frontend, never
included in any response. Keep `.env` out of version control (already in
`.gitignore`).

## Re-ingesting after manual updates

Edit the relevant chunk(s) in `app/data/caregiver_chunks.json` or
`admin_chunks.json` (keep section/page accurate, keep `role` as either
`caregiver` or `admin`), then re-run:

```bash
python scripts/ingest_manuals.py
```

If you ever change chunk IDs or remove chunks, delete the `chroma_data`
folder first and re-run ingestion fresh — `upsert` won't remove orphaned
old IDs on its own.