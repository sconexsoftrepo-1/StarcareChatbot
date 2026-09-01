"""
Lazily-created Azure OpenAI async client, shared by rag_service and llm_service.

Why lazy (created on first use, not at import time):
The OpenAI SDK raises immediately if constructed without an api_key. Building
the client at import time meant a missing AZURE_OPENAI_API_KEY took the whole
process down on startup — on Azure that shows up only as an opaque
"503 Service Unavailable" with /health and /docs unreachable too. Creating it on
first call instead lets the app boot; chat/embedding calls then fail with a
clear message while everything else stays up and debuggable.
"""

from functools import lru_cache

import httpx
from openai import AsyncAzureOpenAI

from app.config import settings


class AzureOpenAINotConfigured(RuntimeError):
    """AZURE_OPENAI_API_KEY is missing — chat/embeddings can't work until it's set."""


@lru_cache(maxsize=1)
def get_async_client() -> AsyncAzureOpenAI:
    if not settings.AZURE_OPENAI_API_KEY:
        raise AzureOpenAINotConfigured(
            "AZURE_OPENAI_API_KEY is not set. On Azure add it under "
            "App Service -> Settings -> Environment variables -> App settings, "
            "then restart the app."
        )
    return AsyncAzureOpenAI(
        api_key=settings.AZURE_OPENAI_API_KEY,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_version=settings.AZURE_OPENAI_API_VERSION,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
        http_client=httpx.AsyncClient(
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50)
        ),
    )
