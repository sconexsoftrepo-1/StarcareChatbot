import os
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # silence chromadb telemetry noise


class Settings:
    APP_ENV: str = os.getenv("APP_ENV", "development")

    # Azure OpenAI (Microsoft Foundry) — LLM/embeddings config.
    # Note: for Azure, "model" in API calls means the *deployment name*, not the
    # underlying model family name — see AZURE_OPENAI_CHAT_DEPLOYMENT / EMBEDDING_DEPLOYMENT below.
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-5-mini")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = os.getenv(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"
    )
    # Some newer chat-completion deployments (reasoning-tier models) reject a custom
    # temperature and only accept the default. If you hit an error mentioning
    # "temperature", set this to False in .env and redeploy — no code change needed.
    LLM_SEND_TEMPERATURE: bool = os.getenv("LLM_SEND_TEMPERATURE", "true").lower() == "true"

    # Retrieval
    TOP_K: int = int(os.getenv("TOP_K", "6"))
    # Chroma returns cosine DISTANCE (0 = identical, 2 = opposite). We convert to a
    # similarity score (1 - distance/2) and require it to be >= this threshold.
    RAG_SIMILARITY_THRESHOLD: float = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.35"))

    # Chat / sessions (in-memory, single temporary session per user — no DB required)
    MAX_HISTORY_MESSAGES: int = int(os.getenv("MAX_HISTORY_MESSAGES", "8"))
    SESSION_TTL_MINUTES: int = int(os.getenv("SESSION_TTL_MINUTES", "30"))

    # Local vector store (no server / no Docker needed)
    CHROMA_DIR: str = os.getenv("CHROMA_DIR", "./chroma_data")
    CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "starcare_manuals")

    # Optional: simple escalation log (append-only local SQLite file, not required to run)
    ESCALATION_LOG_DB: str = os.getenv("ESCALATION_LOG_DB", "./escalations.db")

    # Concurrency controls for load (200-500 concurrent users)
    # Caps how many embedding/LLM calls are in flight to OpenAI at once. Requests
    # beyond this just wait their turn instead of all firing simultaneously and
    # tripping your OpenAI account's own rate limits. Tune to your OpenAI tier.
    MAX_CONCURRENT_LLM_CALLS: int = int(os.getenv("MAX_CONCURRENT_LLM_CALLS", "15"))
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "2"))

    # Microsoft Foundry / Azure OpenAI per-deployment quota, used to PACE
    # outbound calls so the server stays under Azure's own limit instead of
    # bursting and getting 429s back. Defaults below match Microsoft's
    # documented typical starting quota for a standard-tier GPT-5-family chat
    # deployment (~50K TPM / ~50 RPM) and a much lighter embedding deployment.
    # CHECK YOUR ACTUAL NUMBERS: Foundry portal -> your project -> Management
    # (or Operate) -> Quota, and update these to match exactly.
    AZURE_CHAT_RPM: int = int(os.getenv("AZURE_CHAT_RPM", "50"))
    AZURE_EMBEDDING_RPM: int = int(os.getenv("AZURE_EMBEDDING_RPM", "300"))
    # If a request would have to queue longer than this to get an Azure call
    # slot, fail fast with a 503 instead of holding the HTTP connection open.
    MAX_QUEUE_WAIT_SECONDS: float = float(os.getenv("MAX_QUEUE_WAIT_SECONDS", "20"))

    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))

    # Comma-separated list of allowed frontend origins, e.g.
    # "https://app.starcare.com,https://staging.starcare.com"
    # Do NOT use "*" in production if you ever send cookies/auth headers with
    # credentials — browsers reject wildcard + credentials together anyway.
    CORS_ALLOWED_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
    ]


settings = Settings()