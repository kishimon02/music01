"""Project schema for .mcpj format version 2."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MCPJMeta(BaseModel):
    title: str = "Untitled"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MCPJProjectV2(BaseModel):
    model_config = ConfigDict(extra="allow")

    format_version: int = 2
    meta: MCPJMeta = Field(default_factory=MCPJMeta)
    transport: dict[str, Any] = Field(default_factory=dict)
    tracks: list[dict[str, Any]] = Field(default_factory=list)
    plugins: list[dict[str, Any]] = Field(default_factory=list)
    arrangement: list[dict[str, Any]] = Field(default_factory=list)
    ai_history: list[dict[str, Any]] = Field(default_factory=list)
    assets: dict[str, Any] = Field(default_factory=dict)

    mixer_graph: dict[str, Any] = Field(default_factory=dict)
    builtin_fx_states: dict[str, Any] = Field(default_factory=dict)
    analysis_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    suggestion_history: list[dict[str, Any]] = Field(default_factory=list)
    composition_settings: dict[str, Any] = Field(default_factory=dict)
    instrument_assignments: dict[str, Any] = Field(default_factory=dict)
    midi_clips: dict[str, Any] = Field(default_factory=dict)
    compose_history: list[dict[str, Any]] = Field(default_factory=list)
