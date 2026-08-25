"""
Temporary, in-memory chat session store.

Design choice: the requirement is "only one temporary chat at a time for a user"
with no need to survive a server restart, so we keep it simple — a dict in
process memory, keyed by user_id, with a TTL. No SQL DB required for this.

If you later need sessions to survive a restart / run multiple server processes,
swap this module's storage for Redis or a small SQLite table — the function
signatures below (get_session, add_message, reset_session) would not need to
change at the call sites.
"""

import threading
import time
from typing import Dict, List, TypedDict

from app.config import settings


class Message(TypedDict):
    role: str  # "user" | "assistant"
    content: str


class Session(TypedDict):
    messages: List[Message]
    last_active: float


_sessions: Dict[str, Session] = {}
_lock = threading.Lock()


def _is_expired(session: Session) -> bool:
    return (time.time() - session["last_active"]) > settings.SESSION_TTL_MINUTES * 60


def get_session(user_id: str) -> Session:
    """Return the user's current session, creating a fresh one if it doesn't
    exist yet or has expired. Only one session per user exists at a time —
    starting to chat again after expiry just begins a new temporary session."""
    with _lock:
        session = _sessions.get(user_id)
        if session is None or _is_expired(session):
            session = {"messages": [], "last_active": time.time()}
            _sessions[user_id] = session
        return session


def add_message(user_id: str, role: str, content: str) -> None:
    with _lock:
        session = _sessions.get(user_id)
        if session is None or _is_expired(session):
            session = {"messages": [], "last_active": time.time()}
            _sessions[user_id] = session
        session["messages"].append({"role": role, "content": content})
        session["last_active"] = time.time()
        # keep only the most recent N messages in memory for this session
        max_len = settings.MAX_HISTORY_MESSAGES
        if len(session["messages"]) > max_len:
            session["messages"] = session["messages"][-max_len:]


def reset_session(user_id: str) -> None:
    with _lock:
        _sessions.pop(user_id, None)


def get_recent_history(user_id: str) -> List[Message]:
    # Return a copy, not the live list — callers may hold onto this reference
    # across later add_message() calls in the same request and shouldn't see
    # the current turn retroactively appear in what was meant to be "prior" history.
    return list(get_session(user_id)["messages"])