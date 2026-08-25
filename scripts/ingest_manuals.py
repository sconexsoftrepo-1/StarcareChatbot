"""
Run this once (and again any time the manuals change) to (re)build the local
vector store from the hand-curated, section-based chunks in app/data/.

    python scripts/ingest_manuals.py

Idempotent: each chunk has a fixed id, so re-running this simply upserts the
same rows instead of creating duplicates.
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


def main():
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

    print(f"Done. Collection '{settings.CHROMA_COLLECTION}' now has {collection.count()} chunks "
          f"stored at {settings.CHROMA_DIR}")


if __name__ == "__main__":
    main()