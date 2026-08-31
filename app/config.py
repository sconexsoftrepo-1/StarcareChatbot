import os
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # silence chromadb telemetry noise


class Settings:
    APP_ENV: str = "development"

    # Azure OpenAI (Microsoft Foundry) — LLM/embeddings config.
    # Note: for Azure, "model" in API calls means the *deployment name*, not the
    # underlying model family name — see AZURE_OPENAI_CHAT_DEPLOYMENT / EMBEDDING_DEPLOYMENT below.
    #
    # The API key is the ONLY value read from the environment / .env file.
    # Everything else below is hardcoded directly in this file.
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")

    AZURE_OPENAI_ENDPOINT: str = "https://ai-starcare-hrm-b4ac0.openai.azure.com/"
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-5-mini"
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-small"
    # Some newer chat-completion deployments (reasoning-tier models) reject a custom
    # temperature and only accept the default. If you hit an error mentioning
    # "temperature", flip this to False.
    LLM_SEND_TEMPERATURE: bool = False

    # Retrieval
    TOP_K: int = 6
    # Chroma returns cosine DISTANCE (0 = identical, 2 = opposite). We convert to a
    # similarity score (1 - distance/2) and require it to be >= this threshold.
    RAG_SIMILARITY_THRESHOLD: float = 0.35

    # Chat / sessions (in-memory, single temporary session per user — no DB required)
    MAX_HISTORY_MESSAGES: int = 8
    SESSION_TTL_MINUTES: int = 30

    # Local vector store (no server / no Docker needed)
    CHROMA_DIR: str = "./chroma_data"
    CHROMA_COLLECTION: str = "starcare_manuals"

    # Optional: simple escalation log (append-only local SQLite file, not required to run)
    ESCALATION_LOG_DB: str = "./escalations.db"

    # Concurrency controls for load (200-500 concurrent users)
    # Caps how many embedding/LLM calls are in flight to OpenAI at once. Requests
    # beyond this just wait their turn instead of all firing simultaneously and
    # tripping your OpenAI account's own rate limits. Tune to your OpenAI tier.
    MAX_CONCURRENT_LLM_CALLS: int = 60
    LLM_TIMEOUT_SECONDS: float = 30
    LLM_MAX_RETRIES: int = 2

    # Microsoft Foundry / Azure OpenAI per-deployment quota, used to PACE
    # outbound calls so the server stays under Azure's own limit instead of
    # bursting and getting 429s back. CHECK YOUR ACTUAL NUMBERS: Foundry portal
    # -> your project -> Management (or Operate) -> Quota, and update these
    # to match exactly.
    AZURE_CHAT_RPM: int = 50
    AZURE_EMBEDDING_RPM: int = 300
    # If a request would have to queue longer than this to get an Azure call
    # slot, fail fast with a 503 instead of holding the HTTP connection open.
    MAX_QUEUE_WAIT_SECONDS: float = 20

    RATE_LIMIT_PER_MINUTE: int = 30

    # Comma-separated list of allowed frontend origins, e.g.
    # "https://app.starcare.com,https://staging.starcare.com"
    # Do NOT use "*" in production if you ever send cookies/auth headers with
    # credentials — browsers reject wildcard + credentials together anyway.
    CORS_ALLOWED_ORIGINS: list[str] = []


settings = Settings()