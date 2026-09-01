# chromadb requires sqlite3 >= 3.35.0, but the Azure App Service Python image
# links an older system libsqlite3. Swap in pysqlite3 (which bundles a modern
# SQLite) as the stdlib `sqlite3` module BEFORE anything imports chromadb.
#
# This runs on the first `import app...`, which in both entrypoints (main.py and
# scripts/ingest_manuals.py via `from app.config import settings`) happens before
# chromadb is imported. No-op when pysqlite3 isn't installed (e.g. local dev on a
# machine whose system sqlite3 is already new enough).
try:
    import sys

    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ModuleNotFoundError:
    pass
