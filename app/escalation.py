"""
Optional escalation logging.

This is NOT the in-memory chat session store — it's a separate, small,
append-only local SQLite file used only to keep a record of "I couldn't
answer this" cases so you can follow up later. It is not required for the
chatbot to work; if you don't call /api/v1/support/escalate, this file is
never touched. No Postgres/Docker needed for this scale.
"""

import sqlite3
from datetime import datetime, timezone

from app.config import settings


def _connect():
    conn = sqlite3.connect(settings.ESCALATION_LOG_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS escalations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_number TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT,
            email TEXT,
            issue TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def _generate_ticket_number(conn: sqlite3.Connection) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    cur = conn.execute(
        "SELECT COUNT(*) FROM escalations WHERE ticket_number LIKE ?", (f"STAR-{today}-%",)
    )
    count = cur.fetchone()[0] + 1
    return f"STAR-{today}-{count:04d}"


def log_escalation(user_id: str, role: str, name: str | None, email: str | None, issue: str) -> str:
    conn = _connect()
    try:
        ticket_number = _generate_ticket_number(conn)
        conn.execute(
            """INSERT INTO escalations (ticket_number, user_id, role, name, email, issue, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?)""",
            (
                ticket_number,
                user_id,
                role,
                name,
                email,
                issue,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return ticket_number
    finally:
        conn.close()