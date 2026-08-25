"""
Builds a ready-to-send support email draft when the RAG chatbot can't answer
a question. Deliberately template-based rather than LLM-generated: it's
instant (no extra API call/latency on the fallback path), free, and can't
hallucinate details into an email that goes to a real support inbox.
"""

from datetime import datetime, timezone
from typing import List, Tuple

from app.sessions import Message


def build_support_email_draft(
    user_id: str, role: str, message: str, history: List[Message]
) -> Tuple[str, str]:
    subject = f"Starcare Support Request - {role.capitalize()} - Application Question"

    recent_context = ""
    prior_turns = history[-4:] if history else []
    if prior_turns:
        lines = [f"  {m['role']}: {m['content']}" for m in prior_turns]
        recent_context = "\nRecent conversation for context:\n" + "\n".join(lines) + "\n"

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    body = (
        "Hello Starcare Support Team,\n\n"
        "I was using the in-app Starcare assistant and it could not find enough "
        "information in the current documentation to answer my question below. "
        "Could you please help, or let us know if this should be documented?\n\n"
        f"User ID: {user_id}\n"
        f"Role: {role}\n"
        f"Date/Time: {timestamp}\n"
        f"Question: {message}\n"
        f"{recent_context}\n"
        "Thank you,\n"
        f"{user_id}"
    )

    return subject, body