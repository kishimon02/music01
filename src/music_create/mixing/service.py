"""Mixing service with Analyze -> Suggest -> Preview -> Apply/Revert flow."""

from __future__ import annotations

import os
from concurrent.futures import Future
from typing import Callable
from uuid import uuid4

from music_create.mixing.analysis import submit_analysis_job
from music_create.mixing.fx import FXCapabilityRegistry, clamp_param
from music_create.mixing.mixer_graph import MixerGraph, MixerTrackState, SendState
from music_create.mixing.models import (
    AnalysisMode,
    AnalysisSnapshot,
    BuiltinEffectType,
    BuiltinFXChainState,
    MixProfile,
    Suggestion,
    SuggestionCommand,
    TrackFeatures,
)
from music_create.mixing.suggestion_engine import (
    LLMSuggestionEngine,
    RuleBasedSuggestionEngine,
    SuggestionEngineMode,
    normalize_suggestion_engine,
)

TrackSignalProvider = Callable[[str], list[float]]


class MixingService:
    def __init__(
        self,
        mixer_graph: MixerGraph | None = None,
        capability_registry: FXCapabilityRegistry | None = None,
        track_signal_provider: TrackSignalProvider | None = None,
        suggestion_mode: str | None = None,
        llm_suggestion_engine: LLMSuggestionEngine | None = None,
        fallback_to_rule_on_llm_error: bool = True,
    ) -> None:
        self._mixer_graph = mixer_graph or MixerGraph()
        self._capability_registry = capability_registry or FXCapabilityRegistry(builtin_only=True)
        self._track_signal_provider = track_signal_provider or (lambda _track_id: [0.0] * 2048)
        env_mode = os.getenv("MUSIC_CREATE_SUGGESTION_ENGINE")
        try:
            self._suggestion_mode = normalize_suggestion_engine(suggestion_mode or env_mode)
        except ValueError:
            self._suggestion_mode = "rule-based"
        self._rule_suggester = RuleBasedSuggestionEngine()
        self._llm_suggester = llm_suggestion_engine or LLMSuggestionEngine.from_env()
        self._fallback_to_rule_on_llm_error = fallback_to_rule_on_llm_error
        self._last_suggestion_source: str = self._suggestion_mode
        self._last_suggestion_fallback_reason: str | None = None

        self._analysis_jobs: dict[str, Future[AnalysisSnapshot]] = {}
        self._analysis_results: dict[str, AnalysisSnapshot] = {}
        self._suggestions: dict[str, Suggestion] = {}
        self._commands: dict[str, SuggestionCommand] = {}
        self._command_order: list[str] = []
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

    def suggest(
        self,
        track_id: str,
        profile: MixProfile,
        analysis_id: str | None = None,
        mode: AnalysisMode = AnalysisMode.QUICK,
        engine_mode: str | None = None,
    ) -> list[Suggestion]:
        if profile not in {"clean", "punch", "warm"}:
            raise ValueError(f"Unsupported profile '{profile}'")
        track = self._mixer_graph.ensure_track(track_id)
        if analysis_id is None:
            generated_id = self.analyze([track.track_id], mode=mode)
            snapshot = self.get_snapshot(generated_id)
        else:
            snapshot = self.get_snapshot(analysis_id)
            if track_id not in snapshot.track_features:
                raise KeyError(f"Track '{track_id}' is not included in analysis '{analysis_id}'")
        features = snapshot.track_features[track_id]

        target_mode = normalize_suggestion_engine(engine_mode or self._suggestion_mode)
        suggestions = self._generate_suggestions(
            mode=target_mode,
            track_id=track_id,
            profile=profile,
            features=features,
        )
        for suggestion in suggestions:
            self._suggestions[suggestion.suggestion_id] = suggestion
        return suggestions

    def preview(self, track_id: str, suggestion_id: str, dry_wet: float = 1.0) -> None:
        self._require_builtin_only()
        suggestion = self._get_suggestion(suggestion_id, track_id)
        track = self._mixer_graph.ensure_track(track_id)

        baseline = self._preview_cache.get(track_id)
        if baseline is None:
            baseline = track.fx_chain.clone()
            self._preview_cache[track_id] = baseline
        updated = _apply_param_updates(baseline.clone(), suggestion.param_updates, dry_wet)
        track.fx_chain = updated

    def cancel_preview(self, track_id: str) -> None:
        baseline = self._preview_cache.pop(track_id, None)
        if baseline is None:
            return
        track = self._mixer_graph.ensure_track(track_id)
        track.fx_chain = baseline

    def apply(self, track_id: str, suggestion_id: str) -> str:
        self._require_builtin_only()
        suggestion = self._get_suggestion(suggestion_id, track_id)
        track = self._mixer_graph.ensure_track(track_id)
        self.cancel_preview(track_id)

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
        self._command_order.append(command.command_id)
        return command.command_id

    def revert(self, command_id: str) -> None:
        command = self._commands.get(command_id)
        if command is None:
            raise KeyError(f"Command '{command_id}' not found")
        track = self._mixer_graph.ensure_track(command.track_id)
        self.cancel_preview(command.track_id)
        track.fx_chain = command.before_chain.clone()
        command.applied = False

    def get_command_history(self, track_id: str | None = None) -> list[SuggestionCommand]:
        result: list[SuggestionCommand] = []
        for command_id in reversed(self._command_order):
            command = self._commands[command_id]
            if track_id is not None and command.track_id != track_id:
                continue
            result.append(command)
        return result

    def get_mixer_graph(self) -> MixerGraph:
        return self._mixer_graph

    def get_track_state(self, track_id: str) -> MixerTrackState:
        track = self._mixer_graph.ensure_track(track_id)
        return _clone_track_state(track)

    def set_suggestion_mode(self, mode: str) -> None:
        self._suggestion_mode = normalize_suggestion_engine(mode)

    def get_suggestion_mode(self) -> SuggestionEngineMode:
        return self._suggestion_mode

    def get_last_suggestion_source(self) -> str:
        return self._last_suggestion_source

    def get_last_suggestion_fallback_reason(self) -> str | None:
        return self._last_suggestion_fallback_reason

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

    def _generate_suggestions(
        self,
        mode: SuggestionEngineMode,
        track_id: str,
        profile: MixProfile,
        features: TrackFeatures,
    ) -> list[Suggestion]:
        self._last_suggestion_fallback_reason = None
        if mode == "rule-based":
            self._last_suggestion_source = "rule-based"
            return self._rule_suggester.generate(track_id=track_id, profile=profile, features=features)

        try:
            suggestions = self._llm_suggester.generate(track_id=track_id, profile=profile, features=features)
            self._last_suggestion_source = "llm-based"
            return suggestions
        except Exception as exc:
            if not self._fallback_to_rule_on_llm_error:
                raise
            fallback_reason = _format_fallback_reason(exc)
            self._last_suggestion_source = "rule-based-fallback"
            self._last_suggestion_fallback_reason = fallback_reason
            suggestions = self._rule_suggester.generate(track_id=track_id, profile=profile, features=features)
            for suggestion in suggestions:
                suggestion.reason = f"{suggestion.reason} | fallback={fallback_reason}"
            return suggestions


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


def _clone_track_state(track: MixerTrackState) -> MixerTrackState:
    return MixerTrackState(
        track_id=track.track_id,
        input_gain_db=track.input_gain_db,
        fx_chain=track.fx_chain.clone(),
        fader_db=track.fader_db,
        pan=track.pan,
        sends=[
            SendState(
                target_bus_id=send.target_bus_id,
                level_db=send.level_db,
                pre_fader=send.pre_fader,
            )
            for send in track.sends
        ],
    )


def _format_fallback_reason(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    if not text:
        return "llm_error"
    if len(text) > 120:
        return text[:117] + "..."
    return text
