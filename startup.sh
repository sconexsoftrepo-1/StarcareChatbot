#!/usr/bin/env bash
#
# Self-contained Azure App Service (Linux) startup.
#
# Set this as the Startup Command (Configuration -> General settings):
#     bash startup.sh
#
# Why this exists: Azure only installs requirements.txt if its Oryx build runs
# during deployment (needs the SCM_DO_BUILD_DURING_DEPLOYMENT=true app setting).
# When that isn't happening the container starts with no packages and dies with
# "ModuleNotFoundError: No module named 'uvicorn'". This script removes that
# dependency: it builds a virtualenv on the persistent /home share on the first
# boot and reuses it afterwards, only reinstalling when requirements.txt changes.
#
# First boot does a full pip install (chromadb/onnxruntime compile — a few
# minutes). If Azure kills the container before it finishes, raise the limit:
#     App settings -> WEBSITES_CONTAINER_START_TIME_LIMIT = 1800
set -e

VENV="/home/venv"
STAMP="$VENV/.requirements.sha256"
WANT="$(sha256sum requirements.txt | awk '{print $1}')"

if [ ! -x "$VENV/bin/python" ]; then
    echo "[startup] creating virtualenv at $VENV"
    python -m venv "$VENV"
fi

if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT" ]; then
    echo "[startup] installing requirements.txt (this can take several minutes on first run)"
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/python" -m pip install -r requirements.txt
    echo "$WANT" > "$STAMP"
else
    echo "[startup] requirements unchanged — reusing $VENV"
fi

echo "[startup] launching gunicorn"
exec "$VENV/bin/python" -m gunicorn main:app -c gunicorn.conf.py
