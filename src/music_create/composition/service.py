"""Composition service: suggest, preview, apply and revert."""

from __future__ import annotations

import tempfile
from pathlib import Path

from music_create.composition.llm import CompositionLLMEngine
from music_create.composition.models import ComposeCommand, ComposeMode, ComposeRequest, ComposeSuggestion
from music_create.composition.quantize import normalize_grid
from music_create.composition.rules import generate_rule_suggestions
from music_create.composition.synth import render_clip_to_wav
from music_create.ui.timeline import TimelineState


class CompositionService:
    def __init__(
        self,
        timeline: TimelineState,
        engine_mode: ComposeMode = "rule-based",
        llm_engine: CompositionLLMEngine | None = None,
        fallback_to_rule_on_llm_error: bool = True,
    ) -> None:
        self._timeline = timeline
        self._engine_mode: ComposeMode = engine_mode
        self._llm = llm_engine or CompositionLLMEngine.from_env()
        self._fallback_to_rule_on_llm_error = fallback_to_rule_on_llm_error

        self._suggestions: dict[str, ComposeSuggestion] = {}
        self._commands: dict[str, ComposeCommand] = {}
        self._command_order: list[str] = []
        self._preview_dir = Path(tempfile.gettempdir()) / "music_create" / "compose_preview"
        self._preview_dir.mkdir(parents=True, exist_ok=True)

        self._last_source: str = engine_mode
        self._last_fallback_reason: str | None = None

    def set_engine_mode(self, mode: ComposeMode) -> None:
        self._engine_mode = mode

    def get_engine_mode(self) -> ComposeMode:
        return self._engine_mode

    def suggest(self, request: ComposeRequest, engine_mode: ComposeMode | None = None) -> list[ComposeSuggestion]:
        request.grid = normalize_grid(request.grid)
        request.validate()
        target = engine_mode or self._engine_mode

        self._last_fallback_reason = None
        if target == "rule-based":
            suggestions = generate_rule_suggestions(request)
            self._last_source = "rule-based"
        else:
            try:
                suggestions = self._llm.suggest(request)
                self._last_source = "llm-based"
            except Exception as exc:
                if not self._fallback_to_rule_on_llm_error:
                    raise
                reason = _format_reason(exc)
                suggestions = generate_rule_suggestions(request)
                for item in suggestions:
                    item.source = "rule-based-fallback"
                    item.reason = f"{item.reason} | fallback={reason}"
                self._last_source = "rule-based-fallback"
                self._last_fallback_reason = reason

        for item in suggestions:
            self._suggestions[item.suggestion_id] = item
        return suggestions

    def preview(self, suggestion_id: str) -> Path:
        suggestion = self._get_suggestion(suggestion_id)
        clip = suggestion.clips[0]
        out = self._preview_dir / f"{suggestion.suggestion_id}.wav"
        return render_clip_to_wav(clip, out)

    def apply_to_timeline(self, suggestion_id: str) -> tuple[str, list[str]]:
        suggestion = self._get_suggestion(suggestion_id)
        track_id = suggestion.request.track_id
        self._timeline.ensure_track(track_id, name=f"Track {len(self._timeline.tracks) + 1}")
        existing = self._timeline.clips_for_track(track_id)
        start_bar = 1 if not existing else min(existing[-1].end_bar + 1, self._timeline.bars)

        created_ids: list[str] = []
        for idx, clip in enumerate(suggestion.clips, start=1):
            length_bars = min(max(1, clip.bars), self._timeline.bars)
            if start_bar + length_bars - 1 > self._timeline.bars:
                start_bar = max(1, self._timeline.bars - length_bars + 1)
            name = f"{clip.name} #{idx}"
            timeline_clip = self._timeline.add_clip(
                track_id=track_id,
                clip_type="midi",
                start_bar=start_bar,
                length_bars=length_bars,
                name=name,
                midi_data=clip,
            )
            created_ids.append(timeline_clip.clip_id)
            start_bar = min(timeline_clip.end_bar + 1, self._timeline.bars)

        command = ComposeCommand.new(suggestion_id=suggestion_id, track_id=track_id, created_clip_ids=created_ids)
        self._commands[command.command_id] = command
        self._command_order.append(command.command_id)
        return command.command_id, created_ids

    def revert(self, command_id: str) -> None:
        command = self._commands.get(command_id)
        if command is None:
            raise KeyError(f"ComposeCommand '{command_id}' not found")
        if not command.applied:
            return
        for clip_id in command.created_clip_ids:
            self._timeline.remove_clip(clip_id)
        command.applied = False

    def get_history(self, track_id: str | None = None) -> list[ComposeCommand]:
        items: list[ComposeCommand] = []
        for command_id in reversed(self._command_order):
            command = self._commands[command_id]
            if track_id is not None and command.track_id != track_id:
                continue
            items.append(command)
        return items

    def get_last_source(self) -> str:
        return self._last_source

    def get_last_fallback_reason(self) -> str | None:
        return self._last_fallback_reason

    def _get_suggestion(self, suggestion_id: str) -> ComposeSuggestion:
        suggestion = self._suggestions.get(suggestion_id)
        if suggestion is None:
            raise KeyError(f"ComposeSuggestion '{suggestion_id}' not found")
        return suggestion


def _format_reason(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    if not text:
        return "llm_error"
    return text if len(text) <= 120 else text[:117] + "..."
