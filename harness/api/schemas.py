from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model_backend: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str
    mode: str
