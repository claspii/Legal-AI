"""
Chat-related Pydantic schemas.
"""

from datetime import datetime
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=5000)
    session_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    use_graph: bool = True
    provider: str | None = None  # gemini, openai, custom_trained
    settings: dict | None = None


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    sources: list[dict] | None = None
    reasoning: str | None = None
    metadata: dict | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatSessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_message_preview: str | None = None

    class Config:
        from_attributes = True


class ChatSessionCreate(BaseModel):
    title: str = Field(default="Phiên chat mới", max_length=255)


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionResponse]
    total: int


class ChatMessagesListResponse(BaseModel):
    session_id: str
    messages: list[ChatMessageResponse]
    total: int
