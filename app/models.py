from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="Stable ID for the signed-in user from the Starcare app")
    # TODO: In production, do not trust a role sent by the frontend. Replace this with a
    # role resolved server-side from the Starcare auth/JWT (see api/dependencies note in README).
    role: Literal["caregiver", "admin"] = Field(..., description="Resolved from Starcare auth")
    message: str = Field(..., min_length=1, max_length=2000)

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "u123",
                "role": "caregiver",
                "message": "Why can't I administer this medication?",
            }
        }


class Source(BaseModel):
    document: str
    section: str
    module: str
    page: int


class FollowUp(BaseModel):
    type: Literal["suggested_question", "draft_email", "end_chat"]
    label: str
    # only populated when type == "draft_email"
    subject: Optional[str] = None
    body: Optional[str] = None


class ChatResponse(BaseModel):
    user_id: str
    answer: str
    can_answer: bool
    confidence: float
    sources: List[Source]
    escalation_available: bool
    follow_ups: List[FollowUp]


class ResetRequest(BaseModel):
    user_id: str


class EscalateRequest(BaseModel):
    user_id: str
    role: Literal["caregiver", "admin"]
    name: Optional[str] = None
    email: Optional[str] = None
    issue: str = Field(..., min_length=1, max_length=2000)


class EscalateResponse(BaseModel):
    ticket_number: str
    status: str