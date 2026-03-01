"""Composition public facade."""

from __future__ import annotations

from pathlib import Path

from music_create.composition.models import ComposeCommand, ComposeMode, ComposeRequest, ComposeSuggestion
from music_create.composition.service import CompositionService


class Composition:
    def __init__(self, service: CompositionService) -> None:
        self._service = service

    def set_engine(self, mode: ComposeMode) -> None:
        self._service.set_engine_mode(mode)

    def get_engine(self) -> ComposeMode:
        return self._service.get_engine_mode()

    def suggest(self, request: ComposeRequest, engine_mode: ComposeMode | None = None) -> list[ComposeSuggestion]:
        return self._service.suggest(request=request, engine_mode=engine_mode)

    def preview(self, suggestion_id: str) -> Path:
        return self._service.preview(suggestion_id=suggestion_id)

    def apply_to_timeline(self, suggestion_id: str) -> tuple[str, list[str]]:
        return self._service.apply_to_timeline(suggestion_id=suggestion_id)

    def revert(self, command_id: str) -> None:
        self._service.revert(command_id=command_id)

    def get_history(self, track_id: str | None = None) -> list[ComposeCommand]:
        return self._service.get_history(track_id=track_id)

    def get_last_source(self) -> str:
        return self._service.get_last_source()

    def get_last_fallback_reason(self) -> str | None:
        return self._service.get_last_fallback_reason()

