# Deploying to Azure App Service (Linux, Python 3.11)

Target app: `chatbot-starcare-prod` — https://chatbot-starcare-prod.azurewebsites.net

## What the code already handles

- **Config is in code, not in a file.** `app/config.py` hardcodes the endpoint,
  deployment names, retrieval settings, rate limits, etc. The **only** value read
  from the environment is `AZURE_OPENAI_API_KEY`. The old `env` file is no longer
  used in production (it was never actually loaded there).
- **Writable paths on Azure.** When running on App Service (`WEBSITE_INSTANCE_ID`
  is set) the escalation SQLite log goes to `/home/data/` (persistent) and the
  Chroma vector store goes to `/tmp/starcare/` (rebuilt from `app/data/*.json`
  on every startup — it's only ~40 chunks).
- **Startup.** Served by gunicorn + Uvicorn worker via `gunicorn.conf.py`
  (binds `$PORT`, single worker — see the file's comments). You must set the
  Startup Command in the portal (step 2 below) — it can't be set from the
  workflow with publish-profile auth. `python main.py` still works for local dev.
- **Boots even without the key.** If `AZURE_OPENAI_API_KEY` is missing the app
  still starts (so `/health` and `/docs` work); chat just returns the fallback
  answer until the key is set. It no longer crashes the container.
- **CORS.** Defaults to allowing every origin so the widget works immediately.

## One-time Azure setup

### 1. App setting (the API key)

App Service → **Settings → Environment variables → App settings → + Add**:

| Name | Value |
|---|---|
| `AZURE_OPENAI_API_KEY` | *your Azure OpenAI key* |

Optional, to restrict browser origins later:

| Name | Value |
|---|---|
| `CORS_ALLOWED_ORIGINS` | `https://app.starcare.com,https://portal.starcare.com` |

Leave `SCM_DO_BUILD_DURING_DEPLOYMENT` = `true` (set automatically when you
connect GitHub — this is what runs `pip install`).

### 2. Startup command (required — set it in the portal)

App Service → **Settings → Configuration → General settings → Startup Command**:

```
python -m gunicorn main:app -c gunicorn.conf.py
```

Then **Save** (the app restarts). `python main.py` also works but gunicorn +
Uvicorn worker is the supported setup on App Service.

> This **cannot** be set from the GitHub Actions workflow: `azure/webapps-deploy`
> rejects `startup-command` when it authenticates with a publish profile
> (`Error: startup-command is not a valid input ... with publish-profile auth
> scheme`). The portal setting is the only way unless you switch the workflow to
> Azure-login (OIDC) auth. It persists across deploys; you only re-set it if you
> disconnect/reconnect the Deployment Center.

### 3. Deploy

Push to `main` → GitHub Actions builds and deploys. Watch it in
**Deployment Center → Logs**.

## Verifying the deployment

```bash
curl https://chatbot-starcare-prod.azurewebsites.net/health
# {"status":"ok"}

curl -X POST https://chatbot-starcare-prod.azurewebsites.net/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"test1","role":"caregiver","message":"How do I administer a medication?"}'
```

Interactive docs: `https://chatbot-starcare-prod.azurewebsites.net/docs`

## Troubleshooting

- **App won't start / "Application Error"** — check the Startup Command is
  `python main.py`. View live logs: App Service → **Log stream**.
- **Chat returns "not enough information" for everything** — the startup manual
  ingestion failed. Almost always a bad/missing `AZURE_OPENAI_API_KEY`, or the
  chat/embedding deployment names in `app/config.py` don't match Foundry.
- **429 / "receiving too many requests"** — Azure OpenAI deployment quota.
  Update `AZURE_CHAT_RPM` / `AZURE_EMBEDDING_RPM` in `app/config.py` to match
  your real Foundry quota.
- **Slow first request after deploy** — cold start rebuilds the vector store
  (~40 embedding calls). Subsequent requests are fast.
