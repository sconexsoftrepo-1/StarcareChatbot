# Starcare Support Chatbot — RAG Backend (V1, no Docker)

A small FastAPI backend that answers "how do I use Starcare" questions **only**
from the Caregiver and Admin manuals, respecting the user's role. Scoped down
on purpose: no Docker, no Postgres, no ticket/email system — just the chatbot.

## Why no SQL database

Two separate things were in scope for a DB, and neither needs one at this size:

1. **Chat sessions** — you asked for one temporary chat per user. That's a
   perfect fit for an in-memory store: a Python dict keyed by `user_id`, with
   a TTL (`SESSION_TTL_MINUTES`, default 30). No setup, no server, resets
   automatically. See `app/sessions.py`. Trade-off: if you restart the
   server, active sessions are lost — acceptable for a "temporary" chat.
2. **The manuals themselves** — instead of Postgres+pgvector, this uses
   **Chroma**, a vector store that's just a local folder (`./chroma_data`).
   `pip install` is all it takes, nothing to run separately.

If later you want chat history to survive a restart, or want persistent
support tickets with email, that's a small addition (SQLite is enough at 200
users) — it doesn't require touching how the chat/RAG logic works.

## How the RAG works

1. Both manuals were pre-chunked **by hand, by section** (not auto-split) —
   see `app/data/caregiver_chunks.json` and `app/data/admin_chunks.json`.
   Each chunk keeps the manual's real section name, module, page number, and
   role tag, so "Overdue Section" stays one coherent chunk instead of being
   cut mid-workflow.
2. `scripts/ingest_manuals.py` embeds each chunk (OpenAI embeddings) and
   upserts it into a local Chroma collection. It's idempotent — chunk IDs are
   fixed, so re-running it just updates the same rows.
3. On each chat message, the backend:
   - embeds the question (folding in the previous user turn, so follow-ups
     like *"what if it's overdue?"* still retrieve the right section)
   - retrieves the top-K chunks, **filtered to `role = caregiver` or
     `role = admin` (matching the requester) plus `role = shared`** — a
     caregiver can never retrieve an admin-only chunk, full stop
   - drops any retrieved chunk below `RAG_SIMILARITY_THRESHOLD`
   - if nothing survives, returns the fixed "not enough information" message
     and skips the LLM call entirely (no chance to hallucinate)
   - otherwise asks the LLM to answer **using only that context**, with a
     system prompt that forbids inventing buttons/workflows/permissions and
     forbids medical advice, and to return structured JSON
     (`answer`, `can_answer`, `confidence`)

## Follow-up questions

The last `MAX_HISTORY_MESSAGES` turns for a user are kept in memory and sent
to the LLM as conversation context, so a second question like *"what if it's
overdue?"* is understood in light of the first. Retrieval also folds in the
prior user turn (see `build_retrieval_query`) so the right manual section
gets pulled even when the follow-up alone is too short to embed well.

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
# edit .env and set OPENAI_API_KEY

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
→ returns `can_answer: false` and the fallback message, because no
caregiver-tagged or shared chunk covers Admin-only MVR approval.

Reset a user's temporary session:
```bash
curl -X POST http://localhost:8000/api/v1/chat/reset -d '{"user_id":"u1"}' -H "Content-Type: application/json"
```

Log an escalation (optional, writes to a local SQLite file, no server needed):
```bash
curl -X POST http://localhost:8000/api/v1/support/escalate \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","role":"caregiver","issue":"HTTP 504 when saving Monitoring"}'
```

## Concurrency at ~200 users

- All I/O (LLM calls, embeddings, Chroma queries) runs through async FastAPI
  endpoints.
- The OpenAI client and Chroma client are created **once at import time** and
  reused for every request — no per-request/per-user client or model
  instantiation.
- A simple in-memory sliding-window rate limiter caps requests per user per
  minute (`RATE_LIMIT_PER_MINUTE`).

## API keys

`OPENAI_API_KEY` only ever lives in `.env` / environment variables on the
server. It's never sent to or read by the frontend, never included in any
response, and `.env` should stay out of version control (add it to
`.gitignore`).

## Swapping the LLM provider later

`app/llm_service.py` and `app/rag_service.py` both create an `OpenAI(...)`
client using `OPENAI_BASE_URL`. Any OpenAI-compatible endpoint (Azure OpenAI,
a local vLLM/Ollama server, etc.) works by changing `OPENAI_BASE_URL` /
`OPENAI_API_KEY` / `LLM_MODEL` / `EMBEDDING_MODEL` in `.env` — no code
changes needed elsewhere.

## Re-ingesting after manual updates

Edit the relevant chunk(s) in `app/data/caregiver_chunks.json` or
`admin_chunks.json` (keep section/page accurate), then re-run:

```bash
python scripts/ingest_manuals.py
```
