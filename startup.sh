#!/usr/bin/env bash
# Azure App Service (Linux) startup command.
#
# Configured automatically by the GitHub Actions deploy step
# (.github/workflows/main_chatbot-starcare-prod.yml -> startup-command).
# You can also set it by hand in the portal:
#   App Service -> Settings -> Configuration -> General settings
#   -> Startup Command:  bash startup.sh      (or simply:  python main.py)
#
# main.py starts uvicorn itself and binds the port Azure provides
# ($PORT, else $WEBSITES_PORT, else 8000).
set -e
python main.py
