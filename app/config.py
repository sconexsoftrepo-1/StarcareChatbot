import os
from pathlib import Path

from dotenv import load_dotenv

# Local dev: values are read from a `.env` file next to this repo if present.
# On Azure App Service there is no .env file — the one value we need
# (AZURE_OPENAI_API_KEY) is provided as an App Service "App setting" instead,
# which arrives as a normal environment variable. load_dotenv() is a no-op there.
load_dotenv()
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # silence chromadb telemetry noise

# WEBSITE_INSTANCE_ID is always set inside an Azure App Service container and
# never locally, so it's a reliable "are we running on Azure" switch.
ON_AZURE: bool = bool(os.getenv("WEBSITE_INSTANCE_ID"))

# Where to keep files the app writes at runtime (the Chroma vector store and the
# escalation SQLite log).
#   - Azure Linux App Service: /home is the persistent, writable mounted share;
#     the app's own folder (/home/site/wwwroot) can be read-only when the app is
#     run from a deployment package.
#   - Local dev: the project root, same as before.
_DATA_DIR = Path("/home/data") if ON_AZURE else Path(__file__).resolve().parent.parent
try:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # Very defensive: if /home/data somehow isn't writable, fall back to /tmp so
    # the app still boots (the escalation log is the only thing that lands here).
    _DATA_DIR = Path("/tmp/starcare")
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

# The Chroma store is rebuilt from app/data/*.json on every startup (see the
# FastAPI startup event in main.py) and it's only ~40 small chunks, so keeping it
# on fast local disk and re-embedding on a cold start is cheaper and more robust
# than carrying a SQLite file across deploys on the network share.
_CHROMA_DIR = Path("/tmp/starcare/chroma_data") if ON_AZURE else _DATA_DIR / "chroma_data"
_CHROMA_DIR.parent.mkdir(parents=True, exist_ok=True)


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    APP_ENV: str = os.getenv("APP_ENV", "production" if ON_AZURE else "development")

    # --- Azure OpenAI (Microsoft Foundry) -------------------------------------
    # The API KEY is the ONLY secret and the ONLY value read from the
    # environment. Set it once, outside the code:
    #   Local dev : AZURE_OPENAI_API_KEY=... in a .env file (git-ignored)
    #   Azure     : App Service -> Settings -> Environment variables ->
    #               App settings -> New:  AZURE_OPENAI_API_KEY = <your key>
    # Everything else below is fixed here in code (it used to be duplicated in
    # the `env` file, which was never actually loaded in production).
    #
    # For Azure OpenAI, "deployment" is the name you gave the model in the
    # Foundry portal, not the underlying model family.
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_ENDPOINT: str = "https://ai-starcare-hrm-b4ac0.openai.azure.com/"
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-5-mini"
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-small"
    # Some newer chat deployments (reasoning-tier models, e.g. gpt-5-mini) reject
    # a custom temperature and only accept the default. Keep this False for those.
    LLM_SEND_TEMPERATURE: bool = False

    # --- Retrieval ----------------------------------------------------------
    TOP_K: int = 6
    # Chroma returns cosine DISTANCE (0 = identical, 2 = opposite). We convert to
    # a similarity score (1 - distance/2) and require it to be >= this threshold.
    RAG_SIMILARITY_THRESHOLD: float = 0.35

    # --- Chat sessions (in-memory, single temporary session per user) ------
    MAX_HISTORY_MESSAGES: int = 8
    SESSION_TTL_MINUTES: int = 30

    # --- Local vector store (file-based Chroma, no server / no Docker) -----
    CHROMA_DIR: str = str(_CHROMA_DIR)
    CHROMA_COLLECTION: str = "starcare_manuals"

    # --- Escalation log (append-only local SQLite file) -------------------
    ESCALATION_LOG_DB: str = str(_DATA_DIR / "escalations.db")

    # --- Concurrency controls for load (200-500 concurrent users) ---------
    # Caps how many embedding/LLM calls are in flight to Azure OpenAI at once.
    MAX_CONCURRENT_LLM_CALLS: int = 60
    LLM_TIMEOUT_SECONDS: float = 30
    LLM_MAX_RETRIES: int = 2

    # Azure OpenAI per-deployment quota, used to PACE outbound calls so the
    # server stays under Azure's own limit instead of bursting into 429s.
    # CHECK YOUR ACTUAL NUMBERS in the Foundry portal -> Quota and update these.
    AZURE_CHAT_RPM: int = 50
    AZURE_EMBEDDING_RPM: int = 300
    # If a request would have to queue longer than this for an Azure call slot,
    # fail fast with a 503 instead of holding the HTTP connection open.
    MAX_QUEUE_WAIT_SECONDS: float = 20

    RATE_LIMIT_PER_MINUTE: int = 30

    # --- CORS -------------------------------------------------------------
    # Default: allow any origin, so the chat widget works from any site the
    # moment it's deployed. To lock it down, set an App setting
    #   CORS_ALLOWED_ORIGINS = https://app.starcare.com,https://portal.starcare.com
    # (comma-separated). When a specific list is set, credentialed requests are
    # allowed; with the "*" default they are not (browsers forbid that combo).
    CORS_ALLOWED_ORIGINS: list[str] = _csv_env("CORS_ALLOWED_ORIGINS") or ["*"]


settings = Settings()
