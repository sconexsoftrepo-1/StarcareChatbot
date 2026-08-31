"""
Builds/refreshes the local vector store from the hand-curated, section-based
chunks in app/data/.

Runs automatically once, on API startup (see app/main.py's startup event) —
you no longer need to run this by hand for a normal first run.

You only need to run it manually when you've edited the manual chunks and
want to re-embed without restarting the server:

    python scripts/ingest_manuals.py

Idempotent: each chunk has a fixed id, so re-running this simply upserts the
same rows instead of creating duplicates (whether triggered by startup or by
hand).
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import AzureOpenAI

from app.config import settings

CHUNK_FILES = [
    "app/data/caregiver_chunks.json",
    "app/data/admin_chunks.json",
]


def run_ingestion() -> int:
    """(Re)builds the Chroma collection from the manual chunk files.

    Returns the number of chunks now stored in the collection. Safe to call
    repeatedly (upsert on fixed chunk ids) — used both by the FastAPI startup
    event and by this script's CLI entrypoint below.
    """
    if not settings.AZURE_OPENAI_API_KEY or not settings.AZURE_OPENAI_ENDPOINT:
        raise SystemExit(
            "AZURE_OPENAI_API_KEY and/or AZURE_OPENAI_ENDPOINT are not set. Add them to your .env file first."
        )

    client = AzureOpenAI(
        api_key=settings.AZURE_OPENAI_API_KEY,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )
    chroma = chromadb.PersistentClient(
        path=settings.CHROMA_DIR,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = chroma.get_or_create_collection(
        name=settings.CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    all_chunks = []
    for path in CHUNK_FILES:
        with open(path, "r", encoding="utf-8") as f:
            all_chunks.extend(json.load(f))

    print(f"Loaded {len(all_chunks)} chunks from {len(CHUNK_FILES)} file(s).")

    ids, documents, metadatas, embeddings = [], [], [], []
    for chunk in all_chunks:
        emb = client.embeddings.create(
            model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT, input=chunk["content"]
        ).data[0].embedding

        ids.append(chunk["id"])
        documents.append(chunk["content"])
        metadatas.append(
            {
                "document": chunk["document"],
                "role": chunk["role"],
                "module": chunk["module"],
                "section": chunk["section"],
                "page": chunk["page"],
            }
        )
        embeddings.append(emb)
        print(f"  embedded: {chunk['id']}")

    # upsert = safe to re-run without creating duplicates
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)

    count = collection.count()
    print(f"Done. Collection '{settings.CHROMA_COLLECTION}' now has {count} chunks "
          f"stored at {settings.CHROMA_DIR}")
    return count


if __name__ == "__main__":
    run_ingestion()