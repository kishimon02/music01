"""FastAPI request/response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    track_ids: list[str] = Field(min_length=1)
    mode: Literal["quick", "full"] = "quick"


class AnalyzeResponse(BaseModel):
    analysis_id: str


class SuggestRequest(BaseModel):
    track_id: str
    profile: Literal["clean", "punch", "warm"] = "clean"
    analysis_id: str | None = None
    mode: Literal["quick", "full"] = "quick"
    suggestion_engine: Literal["rule-based", "llm-based"] | None = None


class SuggestionCandidate(BaseModel):
    suggestion_id: str
    track_id: str
    profile: str
    variant: str
    score: float
    reason: str
    param_updates: dict[str, dict[str, float]]


class SuggestResponse(BaseModel):
    candidates: list[SuggestionCandidate]
