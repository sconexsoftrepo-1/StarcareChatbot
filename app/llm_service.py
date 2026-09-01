"""
LLM generation, strictly grounded in the retrieved manual chunks.

The async client is created once at import time and reused across requests
(no per-request/per-user client creation). The call itself is awaited, so
under concurrent load one user's slow LLM call doesn't block the event loop
for anyone else — and it shares the same semaphore as embeddings
(app.rag_service.llm_semaphore) so total concurrent OpenAI calls stay bounded
during a burst of 200-500 simultaneous users.
"""

import json
from typing import List

from app.azure_client import get_async_client
from app.config import settings
from app.rag_service import RetrievedChunk, llm_semaphore
from app.rate_limiter import AsyncRateLimiter

# Paces chat completion calls to stay under the Azure deployment's own RPM
# quota — this is the pool that was actually failing (embeddings held up fine).
chat_rate_limiter = AsyncRateLimiter(
    rate_per_minute=settings.AZURE_CHAT_RPM, max_wait_seconds=settings.MAX_QUEUE_WAIT_SECONDS
)

SYSTEM_PROMPT = """You are the Starcare Application Support Assistant.

Rules you must follow at all times:
- Answer ONLY using the "CONTEXT" chunks provided below. Do not use outside knowledge.
- Never invent features, buttons, workflows, or permissions that are not in the context.
- The user's role is {role}. Never describe Admin-only functionality to a caregiver,
  even if it appears in the context (it won't, but treat this as a hard rule).
- This assistant explains how to use the Starcare application. It is NOT a medical
  decision-making system. If the user asks what medication/dosage a patient should
  receive (a clinical question, not an app-usage question), do not answer it — say
  that is a medical decision outside what this assistant can help with, and that the
  application only supports recording/administering medication per clinical orders.
- If the context does not contain enough information to answer, set can_answer to
  false and say so plainly. Do not guess or fill gaps with plausible-sounding detail.
- Format the "answer" field as concise bullet points, not a paragraph. Use
  "\n- " between points (a literal newline followed by a dash and a space)
  inside the JSON string. Each point should be one short, standalone fact or
  step — no point should itself run more than one sentence. Use 2-5 points
  for a normal answer.
- Some context chunks describe a single screen; others describe a multi-step flow
  that already stitches several screens together (labeled as a "Workflow" or "Flow"
  section). If the retrieved context includes a flow chunk, or the question asks
  "what happens next / walk me through / what's the process", format the bullet
  points as an ordered sequence ("1. ", "2. ", ... instead of "- ") so the steps
  read in order. Only include steps that are actually present in the context.
- Use the recent conversation history only to resolve follow-up questions
  (e.g. "what if it's overdue?" following a question about administering medication).
  Do not let it override the role or grounding rules above.
- If (and only if) can_answer is true, also suggest up to 2 short, natural
  follow-up questions this {role} might reasonably ask next. Every suggested
  question MUST be answerable using ONLY the CONTEXT chunks given to you in
  this same request — the same source you used for the answer above. Do not
  suggest a question just because it sounds like something the app probably
  supports; if you have not seen the answer to it in this CONTEXT, do not
  suggest it. It is fine, and expected, to return fewer than 2, or an empty
  list, if the context does not clearly support additional questions.

Respond with ONLY a JSON object, no markdown fences, in exactly this shape:
{{
  "answer": "<bullet-point answer, e.g. \\n- First point\\n- Second point>",
  "can_answer": true or false,
  "confidence": <float 0.0-1.0, your own confidence the context fully answers this>,
  "follow_up_questions": ["<question 1>", "<question 2>"]
}}
"""


def _format_context(chunks: List[RetrievedChunk]) -> str:
    if not chunks:
        return "(no relevant documentation was retrieved)"
    parts = []
    for c in chunks:
        parts.append(
            f"[{c['document']} -> {c['module']} -> {c['section']} (page {c['page']})]\n{c['content']}"
        )
    return "\n\n".join(parts)


async def generate_answer(
    message: str,
    role: str,
    chunks: List[RetrievedChunk],
    history: List[dict],
) -> dict:
    context_text = _format_context(chunks)

    history_text = ""
    if history:
        turns = [f"{m['role']}: {m['content']}" for m in history[-settings.MAX_HISTORY_MESSAGES:]]
        history_text = "Recent conversation:\n" + "\n".join(turns) + "\n\n"

    user_content = (
        f"{history_text}CONTEXT:\n{context_text}\n\n"
        f"Current question from a {role}: {message}"
    )

    await chat_rate_limiter.acquire()
    async with llm_semaphore:
        create_kwargs = dict(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(role=role)},
                {"role": "user", "content": user_content},
            ],
        )
        if settings.LLM_SEND_TEMPERATURE:
            create_kwargs["temperature"] = 0
        completion = await get_async_client().chat.completions.create(**create_kwargs)

    raw = completion.choices[0].message.content
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = {
            "answer": "I could not find enough information about this in the Starcare user manual.",
            "can_answer": False,
            "confidence": 0.0,
        }

    parsed.setdefault("answer", "I could not find enough information about this in the Starcare user manual.")
    parsed.setdefault("can_answer", False)
    parsed.setdefault("confidence", 0.0)
    parsed.setdefault("follow_up_questions", [])
    if not isinstance(parsed.get("follow_up_questions"), list):
        parsed["follow_up_questions"] = []
    return parsed