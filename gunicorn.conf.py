"""
Gunicorn config for Azure App Service (Linux).

Startup Command (App Service -> Settings -> Configuration -> General settings):

    python -m gunicorn main:app -c gunicorn.conf.py

`main:app` is the FastAPI (ASGI) instance in main.py, served through Uvicorn's
worker class.
"""

import os

# Azure passes the port the container must listen on via $PORT. Fall back to
# 8000 (Azure's historical default, and what `python main.py` uses locally).
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# ASGI worker (FastAPI). Without this gunicorn assumes WSGI and the app fails.
worker_class = "uvicorn.workers.UvicornWorker"

# This app keeps chat sessions, the rate limiter and the Chroma vector store in
# per-process memory, and several processes writing the same local Chroma SQLite
# file can deadlock. Default to ONE worker: the app is fully async and I/O-bound
# (it mostly awaits Azure OpenAI), so a single worker handles high concurrency
# well. To scale out: move sessions to Redis and Chroma to a shared/served
# instance first, then raise this via the WEB_CONCURRENCY app setting.
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))

# The first request after a cold start rebuilds the vector store (~40 embedding
# calls). Give the worker room, and match Azure's front-end idle timeout.
timeout = 230
graceful_timeout = 30
keepalive = 5

# Recycle workers periodically as a guard against slow leaks.
max_requests = 1000
max_requests_jitter = 50

# Log to stdout/stderr so it shows up in Azure Log stream.
accesslog = "-"
errorlog = "-"
loglevel = "info"
