import asyncio
import logging
import os
import sys
import time
import uuid
from collections import defaultdict, deque

import openai
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings

# scripts/ lives outside the app package (kept there so it can also be run by
# hand: `python scripts/ingest_manuals.py`, e.g. after editing the manuals).
# Add it to sys.path so it can be imported here too, and called automatically
# on API startup below instead of requiring that manual step for a first run.
# main.py now lives at the project root (sibling of app/ and scripts/), not
# inside app/. scripts/ is a direct sibling here, so no ".." needed.
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts"))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from app.models import (
    ChatRequest,
    ChatResponse,
    EscalateRequest,
    EscalateResponse,
    FollowUp,
    ResetRequest,
    Source,
)
from app import sessions
from app.rag_service import retrieve, retrieve_combined, filter_by_threshold
from app.llm_service import generate_answer
from app.escalation import log_escalation
from app.email_draft import build_support_email_draft
from app.rate_limiter import LocallyRateLimited
from ingest_manuals import run_ingestion  # scripts/ingest_manuals.py, see sys.path setup above

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("starcare-rag")

app = FastAPI(
    title="Starcare Support Chatbot API",
    description="Role-aware RAG chatbot answering questions from the Starcare Caregiver and Admin manuals only.",
    version="1.0.0",
)

# CORS: only origins listed in CORS_ALLOWED_ORIGINS (.env) may call this API
# from a browser. If that list is empty (e.g. local dev with nothing set),
# fall back to allowing localhost dev servers only — never a silent "*".
_cors_origins = settings.CORS_ALLOWED_ORIGINS or [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS allowed origins: %s", _cors_origins)


@app.on_event("startup")
async def ingest_manuals_on_startup():
    # Ensures the Chroma collection is built/up to date before the API starts
    # accepting chat requests — no separate manual `python scripts/ingest_manuals.py`
    # step needed for a normal run. Idempotent (upsert on fixed chunk ids), so
    # this is safe to run on every startup, including restarts.
    # Runs in a worker thread (it's blocking sync code) so it doesn't stall
    # the event loop or any other startup work.
    logger.info("Running manual ingestion...")
    try:
        count = await asyncio.to_thread(run_ingestion)
        logger.info("Manual ingestion complete: %d chunks in collection.", count)
    except Exception:
        logger.exception(
            "Manual ingestion failed on startup. The API will still start, but "
            "chat requests may return 'not enough information' until this is fixed "
            "(check AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT and app/data/*.json)."
        )


FALLBACK_ANSWER = (
    "I could not find enough information about this in the Starcare user manual. "
    "You can contact support and provide a bit more detail about the issue."
)

# --- very simple in-memory rate limiter (per user_id, sliding 60s window) ---
_request_log: dict[str, deque] = defaultdict(deque)


def _check_rate_limit(user_id: str):
    now = time.time()
    window = _request_log[user_id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many requests, please slow down.")
    window.append(now)


@app.exception_handler(LocallyRateLimited)
async def local_rate_limit_handler(request: Request, exc: LocallyRateLimited):
    # Our own pacer decided the queue was too long, rather than round-tripping
    # to Azure and getting a 429 back. Same user-facing message either way —
    # the distinction only matters for server-side logs/debugging.
    logger.warning("Local rate limiter queue exceeded max wait: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "The assistant is receiving too many requests right now. Please try again in a moment."
        },
    )


@app.exception_handler(openai.RateLimitError)
async def azure_rate_limit_handler(request: Request, exc: openai.RateLimitError):
    # This means Azure itself rejected the request — the deployment's
    # tokens-per-minute/requests-per-minute quota is exhausted. Not a bug in
    # this server; surfaced as a distinct, honest status so the frontend can
    # show "please try again shortly" instead of a generic error, and so it's
    # never confused with an actual server-side failure in logs or metrics.
    logger.warning("Azure OpenAI rate limit hit: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "The assistant is receiving too many requests right now. Please try again in a moment."
        },
    )


@app.exception_handler(openai.APIError)
async def azure_api_error_handler(request: Request, exc: openai.APIError):
    logger.warning("Azure OpenAI API error: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "The assistant is temporarily unavailable. Please try again in a moment."},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.get("/health", tags=["health"])
@app.get("/api/v1/health", tags=["health"])
async def health():
    return {"status": "ok"}


@app.post("/api/v1/chat", response_model=ChatResponse, tags=["chat"])
async def chat(payload: ChatRequest):
    request_id = str(uuid.uuid4())
    start = time.time()
    _check_rate_limit(payload.user_id)

    history = sessions.get_recent_history(payload.user_id)

    raw_chunks = await retrieve_combined(payload.message, history, payload.role)
    chunks = filter_by_threshold(raw_chunks)

    if not chunks:
        answer_text = FALLBACK_ANSWER
        can_answer = False
        confidence = 0.0
        sources: list[Source] = []
        follow_up_questions: list[str] = []
    else:
        result = await generate_answer(payload.message, payload.role, chunks, history)
        can_answer = bool(result.get("can_answer"))
        confidence = float(result.get("confidence", 0.0))
        answer_text = result.get("answer", FALLBACK_ANSWER)
        follow_up_questions = result.get("follow_up_questions", [])[:2]
        sources = (
            [
                Source(document=c["document"], section=c["section"], module=c["module"], page=c["page"])
                for c in chunks
            ]
            if can_answer
            else []
        )
        if not can_answer:
            answer_text = answer_text or FALLBACK_ANSWER

    sessions.add_message(payload.user_id, "user", payload.message)
    sessions.add_message(payload.user_id, "assistant", answer_text)

    if can_answer:
        follow_ups = []
        for q in follow_up_questions:
            # Verify each suggested follow-up in code, not just by prompt
            # instruction: it must itself retrieve real manual content for
            # this role before we ever show it to the user.
            verify_chunks = filter_by_threshold(await retrieve(q, payload.role))
            if verify_chunks:
                follow_ups.append(FollowUp(type="suggested_question", label=q))
    else:
        # out-of-context fallback: offer a ready-to-send support email draft and
        # a way to end the temporary chat, instead of guessing at more questions
        subject, body = build_support_email_draft(
            payload.user_id, payload.role, payload.message, history
        )
        follow_ups = [
            FollowUp(
                type="draft_email",
                label="Draft an email to the support team about this",
                subject=subject,
                body=body,
            ),
            FollowUp(type="end_chat", label="End the chat"),
        ]

    logger.info(
        "request_id=%s user_id=%s role=%s retrieval_count=%d can_answer=%s confidence=%.2f latency_ms=%d",
        request_id,
        payload.user_id,
        payload.role,
        len(chunks),
        can_answer,
        confidence,
        int((time.time() - start) * 1000),
    )

    return ChatResponse(
        user_id=payload.user_id,
        answer=answer_text,
        can_answer=can_answer,
        confidence=confidence,
        sources=sources,
        escalation_available=not can_answer,
        follow_ups=follow_ups,
    )


@app.post("/api/v1/chat/reset", tags=["chat"])
async def reset_chat(payload: ResetRequest):
    sessions.reset_session(payload.user_id)
    return {"status": "reset"}


@app.post("/api/v1/support/escalate", response_model=EscalateResponse, tags=["support"])
async def escalate(payload: EscalateRequest):
    ticket_number = log_escalation(
        user_id=payload.user_id,
        role=payload.role,
        name=payload.name,
        email=payload.email,
        issue=payload.issue,
    )
    return EscalateResponse(ticket_number=ticket_number, status="OPEN")