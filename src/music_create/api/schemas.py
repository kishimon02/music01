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


class ComposeSuggestRequest(BaseModel):
    track_id: str
    part: Literal["chord", "melody", "drum"]
    key: Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    scale: Literal["major", "minor"] = "major"
    bars: int = Field(default=4, ge=1, le=32)
    style: Literal["pop", "rock", "hiphop", "edm", "ballad"] = "pop"
    grid: Literal["1", "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T", "1/16", "1/16T", "1/32", "1/32T", "1/64"] = "1/16"
    program: int | None = Field(default=None, ge=0, le=127)
    engine_mode: Literal["rule-based", "llm-based"] | None = None


class ComposeSuggestionCandidate(BaseModel):
    suggestion_id: str
    track_id: str
    part: str
    key: str
    scale: str
    bars: int
    style: str
    grid: str
    source: str
    score: float
    reason: str
    note_count: int
    clip_name: str


class ComposeSuggestResponse(BaseModel):
    candidates: list[ComposeSuggestionCandidate]
    source: str
    fallback_reason: str | None = None
