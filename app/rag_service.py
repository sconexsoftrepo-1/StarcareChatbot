"""
Retrieval over the two ingested manuals, with role-based metadata filtering.

Uses a local, file-based Chroma collection (no server, no Docker). Every
chunk is tagged role="caregiver" or role="admin" — no shared/cross-role
category. A caregiver query only ever retrieves role="caregiver" chunks, and
an admin query only ever retrieves role="admin" chunks. Content that both
roles need (e.g. the sign-in/role-access flow) is duplicated as its own
chunk in each role's file rather than shared, so the filter stays a plain
exact match with no cross-role leakage possible.

Everything here is async/non-blocking so that under load (200-500 concurrent
requests) one slow OpenAI call doesn't stall every other in-flight request on
the same process. A semaphore caps how many embedding calls are in flight at
once so a burst of concurrent users doesn't hammer OpenAI's own rate limits.
"""

import asyncio
from typing import List, TypedDict

import chromadb
import httpx
from chromadb.config import Settings as ChromaSettings
from openai import AsyncAzureOpenAI

from app.config import settings
from app.rate_limiter import AsyncRateLimiter

_client = AsyncAzureOpenAI(
    api_key=settings.AZURE_OPENAI_API_KEY,
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_version=settings.AZURE_OPENAI_API_VERSION,
    timeout=settings.LLM_TIMEOUT_SECONDS,
    max_retries=settings.LLM_MAX_RETRIES,
    http_client=httpx.AsyncClient(
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50)
    ),
)
_chroma = chromadb.PersistentClient(
    path=settings.CHROMA_DIR,
    settings=ChromaSettings(anonymized_telemetry=False),
)
_collection = _chroma.get_or_create_collection(
    name=settings.CHROMA_COLLECTION,
    metadata={"hnsw:space": "cosine"},
)

# Shared across all requests in this process — caps concurrent outbound calls
# to OpenAI (embeddings + chat, see llm_service.py) rather than per-endpoint.
llm_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_LLM_CALLS)

# Paces embedding calls to stay under the Azure deployment's own RPM quota.
embedding_rate_limiter = AsyncRateLimiter(
    rate_per_minute=settings.AZURE_EMBEDDING_RPM, max_wait_seconds=settings.MAX_QUEUE_WAIT_SECONDS
)


class RetrievedChunk(TypedDict):
    content: str
    document: str
    module: str
    section: str
    page: int
    similarity: float


async def embed(text: str) -> List[float]:
    await embedding_rate_limiter.acquire()
    async with llm_semaphore:
        resp = await _client.embeddings.create(
            model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT, input=text
        )
    return resp.data[0].embedding


def build_retrieval_query(current_message: str, history: List[dict]) -> str:
    """Fold the previous user turn into the retrieval query so short follow-ups
    like 'what if it is overdue?' still retrieve the right section, without
    an extra LLM call. We only look one turn back to avoid topic drift."""
    prior_user_messages = [m["content"] for m in history if m["role"] == "user"]
    if not prior_user_messages:
        return current_message
    return f"{prior_user_messages[-1]} {current_message}"


def _query_chroma_sync(query_embedding: List[float], role: str):
    return _collection.query(
        query_embeddings=[query_embedding],
        n_results=settings.TOP_K,
        where={"role": role},
    )


async def retrieve(query: str, role: str) -> List[RetrievedChunk]:
    query_embedding = await embed(query)
    # Chroma's query() is synchronous/CPU-bound; run it off the event loop
    # thread so it can't stall other concurrent requests while it runs.
    results = await asyncio.to_thread(_query_chroma_sync, query_embedding, role)

    chunks: List[RetrievedChunk] = []
    if not results["ids"] or not results["ids"][0]:
        return chunks

    for doc, meta, distance in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        similarity = 1 - (distance / 2)  # cosine distance -> similarity in [0,1]
        chunks.append(
            {
                "content": doc,
                "document": meta["document"],
                "module": meta["module"],
                "section": meta["section"],
                "page": meta["page"],
                "similarity": round(similarity, 4),
            }
        )
    return chunks


async def retrieve_combined(current_message: str, history: List[dict], role: str) -> List[RetrievedChunk]:
    """Retrieve using the current question alone, AND (if there's history) also
    combined with the prior turn — then merge, keeping the best score per chunk.

    Why not just use the combined query: if the user switches topics between
    turns (e.g. asks about variance reports, then separately asks about User
    Management), folding the unrelated prior question into the query dilutes
    the embedding and can bury the chunk that actually answers the new,
    unrelated question. Retrieving both ways and merging keeps follow-ups
    working without breaking plain topic switches.
    """
    queries = [current_message]
    combined = build_retrieval_query(current_message, history)
    if combined != current_message:
        queries.append(combined)

    best_by_key: dict = {}
    for q in queries:
        for c in await retrieve(q, role):
            key = (c["document"], c["section"])
            existing = best_by_key.get(key)
            if existing is None or c["similarity"] > existing["similarity"]:
                best_by_key[key] = c

    merged = sorted(best_by_key.values(), key=lambda c: c["similarity"], reverse=True)
    return merged[: settings.TOP_K]


def filter_by_threshold(chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
    return [c for c in chunks if c["similarity"] >= settings.RAG_SIMILARITY_THRESHOLD]