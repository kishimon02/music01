"""Mixing service with Analyze -> Suggest -> Preview -> Apply/Revert flow."""

from __future__ import annotations

from concurrent.futures import Future
from typing import Callable
from uuid import uuid4

from music_create.mixing.analysis import submit_analysis_job
from music_create.mixing.fx import FXCapabilityRegistry, clamp_param
from music_create.mixing.mixer_graph import MixerGraph
from music_create.mixing.models import (
    AnalysisMode,
    AnalysisSnapshot,
    BuiltinEffectType,
    BuiltinFXChainState,
    MixProfile,
    Suggestion,
    SuggestionCommand,
)
from music_create.mixing.suggestions import suggest_from_features

TrackSignalProvider = Callable[[str], list[float]]


class MixingService:
    def __init__(
        self,
        mixer_graph: MixerGraph | None = None,
        capability_registry: FXCapabilityRegistry | None = None,
        track_signal_provider: TrackSignalProvider | None = None,
    ) -> None:
        self._mixer_graph = mixer_graph or MixerGraph()
        self._capability_registry = capability_registry or FXCapabilityRegistry(builtin_only=True)
        self._track_signal_provider = track_signal_provider or (lambda _track_id: [0.0] * 2048)

        self._analysis_jobs: dict[str, Future[AnalysisSnapshot]] = {}
        self._analysis_results: dict[str, AnalysisSnapshot] = {}
        self._suggestions: dict[str, Suggestion] = {}
        self._commands: dict[str, SuggestionCommand] = {}
        self._preview_cache: dict[str, BuiltinFXChainState] = {}

    def analyze(self, track_ids: list[str], mode: AnalysisMode = AnalysisMode.QUICK) -> str:
        normalized_mode = AnalysisMode(mode)
        signals: dict[str, list[float]] = {}
        for track_id in track_ids:
            self._mixer_graph.ensure_track(track_id)
            signals[track_id] = self._track_signal_provider(track_id)

        future = submit_analysis_job(normalized_mode, signals)
        analysis_id = str(uuid4())
        self._analysis_jobs[analysis_id] = future
        return analysis_id

    def get_snapshot(self, analysis_id: str) -> AnalysisSnapshot:
        result = self._analysis_results.get(analysis_id)
        if result:
            return result

        job = self._analysis_jobs.get(analysis_id)
        if job is None:
            raise KeyError(f"Analysis '{analysis_id}' not found")

        completed = job.result()
        completed.analysis_id = analysis_id
        self._analysis_results[analysis_id] = completed
        del self._analysis_jobs[analysis_id]
        return completed

    def suggest(self, track_id: str, profile: MixProfile) -> list[Suggestion]:
        if profile not in {"clean", "punch", "warm"}:
            raise ValueError(f"Unsupported profile '{profile}'")
        track = self._mixer_graph.ensure_track(track_id)
        signal = self._track_signal_provider(track_id)

        analysis_id = self.analyze([track.track_id], mode=AnalysisMode.QUICK)
        snapshot = self.get_snapshot(analysis_id)
        features = snapshot.track_features[track_id]

        suggestions = suggest_from_features(track_id, profile, features)
        for suggestion in suggestions:
            self._suggestions[suggestion.suggestion_id] = suggestion
        return suggestions

    def preview(self, track_id: str, suggestion_id: str, dry_wet: float = 1.0) -> None:
        self._require_builtin_only()
        suggestion = self._get_suggestion(suggestion_id, track_id)
        track = self._mixer_graph.ensure_track(track_id)
        before = track.fx_chain.clone()
        updated = _apply_param_updates(before.clone(), suggestion.param_updates, dry_wet)
        self._preview_cache[track_id] = before
        track.fx_chain = updated

    def apply(self, track_id: str, suggestion_id: str) -> str:
        self._require_builtin_only()
        suggestion = self._get_suggestion(suggestion_id, track_id)
        track = self._mixer_graph.ensure_track(track_id)

        before = track.fx_chain.clone()
        after = _apply_param_updates(before.clone(), suggestion.param_updates, 1.0)
        track.fx_chain = after

        command = SuggestionCommand.new(
            track_id=track_id,
            suggestion_id=suggestion_id,
            before_chain=before,
            after_chain=after.clone(),
        )
        command.applied = True
        self._commands[command.command_id] = command
        return command.command_id

    def revert(self, command_id: str) -> None:
        command = self._commands.get(command_id)
        if command is None:
            raise KeyError(f"Command '{command_id}' not found")
        track = self._mixer_graph.ensure_track(command.track_id)
        track.fx_chain = command.before_chain.clone()
        command.applied = False

    def get_mixer_graph(self) -> MixerGraph:
        return self._mixer_graph

    def _require_builtin_only(self) -> None:
        if not self._capability_registry.builtin_only:
            raise RuntimeError("Current configuration allows external FX; builtin-only guard expected")

    def _get_suggestion(self, suggestion_id: str, track_id: str) -> Suggestion:
        suggestion = self._suggestions.get(suggestion_id)
        if suggestion is None:
            raise KeyError(f"Suggestion '{suggestion_id}' not found")
        if suggestion.track_id != track_id:
            raise ValueError(
                f"Suggestion '{suggestion_id}' belongs to track '{suggestion.track_id}', not '{track_id}'"
            )
        return suggestion


def _apply_param_updates(
    chain: BuiltinFXChainState,
    updates: dict[BuiltinEffectType, dict[str, float]],
    dry_wet: float,
) -> BuiltinFXChainState:
    normalized_mix = min(max(dry_wet, 0.0), 1.0)
    for effect_type, effect_updates in updates.items():
        effect_state = chain.effects[effect_type]
        for param_id, target_value in effect_updates.items():
            current_value = effect_state.parameters[param_id]
            blended_value = current_value + (target_value - current_value) * normalized_mix
            effect_state.parameters[param_id] = clamp_param(effect_type, param_id, blended_value)
    return chain
