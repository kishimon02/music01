"""Public API facade matching the agreed Python interface."""

from __future__ import annotations

from typing import Literal

from music_create.mixing.mixer_graph import MixerTrackState
from music_create.mixing.models import AnalysisSnapshot, Suggestion, SuggestionCommand
from music_create.mixing.service import MixingService


class Mixing:
    def __init__(self, service: MixingService | None = None) -> None:
        self._service = service or MixingService()

    def analyze(self, track_ids: list[str], mode: Literal["quick", "full"] = "quick") -> str:
        return self._service.analyze(track_ids=track_ids, mode=mode)

    def get_snapshot(self, analysis_id: str) -> AnalysisSnapshot:
        return self._service.get_snapshot(analysis_id)

    def suggest(
        self,
        track_id: str,
        profile: Literal["clean", "punch", "warm"],
        analysis_id: str | None = None,
        mode: Literal["quick", "full"] = "quick",
    ) -> list[Suggestion]:
        return self._service.suggest(track_id=track_id, profile=profile, analysis_id=analysis_id, mode=mode)

    def preview(self, track_id: str, suggestion_id: str, dry_wet: float = 1.0) -> None:
        self._service.preview(track_id=track_id, suggestion_id=suggestion_id, dry_wet=dry_wet)

    def apply(self, track_id: str, suggestion_id: str) -> str:
        return self._service.apply(track_id=track_id, suggestion_id=suggestion_id)

    def cancel_preview(self, track_id: str) -> None:
        self._service.cancel_preview(track_id=track_id)

    def revert(self, command_id: str) -> None:
        self._service.revert(command_id=command_id)

    def get_command_history(self, track_id: str | None = None) -> list[SuggestionCommand]:
        return self._service.get_command_history(track_id=track_id)

    def get_track_state(self, track_id: str) -> MixerTrackState:
        return self._service.get_track_state(track_id=track_id)
