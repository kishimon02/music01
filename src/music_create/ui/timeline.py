"""Timeline domain model for DAW-style UI integration."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any
from uuid import uuid4

DEFAULT_TRACK_COLORS: tuple[str, ...] = (
    "#4D8FF4",
    "#66B7FF",
    "#FF8A4C",
    "#74D39E",
    "#E4B84D",
    "#C28EFF",
)


@dataclass(slots=True)
class TimelineTrack:
    track_id: str
    name: str
    instrument_name: str
    program: int | None
    is_drum: bool
    color: str


@dataclass(slots=True)
class TimelineClip:
    clip_id: str
    track_id: str
    name: str
    clip_type: str  # "midi" | "audio"
    start_bar: int
    length_bars: int

    @property
    def end_bar(self) -> int:
        return self.start_bar + self.length_bars - 1


class TimelineState:
    def __init__(
        self,
        bars: int = 64,
        *,
        max_bars: int = 1000,
        expansion_chunk: int = 64,
        expand_threshold_bars: int = 8,
    ) -> None:
        if bars <= 0:
            raise ValueError("bars must be positive")
        if max_bars < bars:
            raise ValueError("max_bars must be >= bars")
        self.bars = bars
        self.max_bars = max_bars
        self.expansion_chunk = max(expansion_chunk, 1)
        self.expand_threshold_bars = max(expand_threshold_bars, 0)
        self.content_end_bar = 1
        self.playhead_bar = 1.0
        self.tracks: dict[str, TimelineTrack] = {}
        self.clips: dict[str, TimelineClip] = {}
        self.midi_clip_data: dict[str, dict[str, Any]] = {}

    def add_track(
        self,
        name: str | None = None,
        *,
        instrument_name: str | None = None,
        program: int | None = 0,
        is_drum: bool = False,
        color: str | None = None,
    ) -> TimelineTrack:
        index = len(self.tracks) + 1
        track_id = f"track-{index}"
        track = TimelineTrack(
            track_id=track_id,
            name=name or f"Track {index}",
            instrument_name=instrument_name or ("Drums" if is_drum else f"Program {program if program is not None else 0}"),
            program=None if is_drum else program,
            is_drum=bool(is_drum),
            color=color or self._default_track_color(index - 1),
        )
        self.tracks[track_id] = track
        return track

    def ensure_track(
        self,
        track_id: str,
        name: str | None = None,
        *,
        instrument_name: str | None = None,
        program: int | None = 0,
        is_drum: bool = False,
        color: str | None = None,
    ) -> TimelineTrack:
        track = self.tracks.get(track_id)
        if track is not None:
            return track
        track = TimelineTrack(
            track_id=track_id,
            name=name or track_id,
            instrument_name=instrument_name or ("Drums" if is_drum else f"Program {program if program is not None else 0}"),
            program=None if is_drum else program,
            is_drum=bool(is_drum),
            color=color or self._default_track_color(len(self.tracks)),
        )
        self.tracks[track_id] = track
        return track

    def add_clip(
        self,
        track_id: str,
        clip_type: str,
        start_bar: int,
        length_bars: int,
        name: str | None = None,
        midi_data: dict[str, Any] | Any | None = None,
    ) -> TimelineClip:
        if track_id not in self.tracks:
            raise KeyError(f"track '{track_id}' not found")
        if clip_type not in {"midi", "audio"}:
            raise ValueError(f"unsupported clip_type '{clip_type}'")
        if start_bar < 1:
            raise ValueError("start_bar must be >= 1")
        if length_bars <= 0:
            raise ValueError("length_bars must be positive")
        clip_end_bar = start_bar + length_bars - 1
        if clip_end_bar > self.max_bars:
            raise ValueError("clip exceeds max timeline bars")
        if clip_end_bar > self.bars:
            self.expand_to_bar(clip_end_bar)

        clip = TimelineClip(
            clip_id=str(uuid4()),
            track_id=track_id,
            name=name or f"{clip_type.upper()} Clip",
            clip_type=clip_type,
            start_bar=start_bar,
            length_bars=length_bars,
        )
        self.clips[clip.clip_id] = clip
        if clip_type == "midi" and midi_data is not None:
            if is_dataclass(midi_data):
                self.midi_clip_data[clip.clip_id] = asdict(midi_data)
            elif hasattr(midi_data, "__dict__"):
                self.midi_clip_data[clip.clip_id] = dict(vars(midi_data))
            else:
                self.midi_clip_data[clip.clip_id] = dict(midi_data)
        self.content_end_bar = max(self.content_end_bar, clip.end_bar)
        return clip

    def remove_clip(self, clip_id: str) -> None:
        if clip_id in self.clips:
            del self.clips[clip_id]
        self.midi_clip_data.pop(clip_id, None)
        self._recompute_content_end_bar()

    def set_playhead_bar(self, bar: float) -> None:
        requested = max(float(bar), 1.0)
        target_bar = max(int(math.ceil(requested)), 1)
        if target_bar > self.max_bars:
            target_bar = self.max_bars
            requested = float(self.max_bars)
        self.ensure_visible_bar(target_bar)
        self.playhead_bar = min(max(requested, 1.0), float(self.bars))

    def tracks_in_order(self) -> list[TimelineTrack]:
        return list(self.tracks.values())

    def clips_for_track(self, track_id: str) -> list[TimelineClip]:
        items = [clip for clip in self.clips.values() if clip.track_id == track_id]
        return sorted(items, key=lambda clip: (clip.start_bar, clip.clip_id))

    def expand_to_bar(self, bar: int) -> int:
        target_bar = max(int(bar), 1)
        if target_bar > self.max_bars:
            raise ValueError("bar exceeds max timeline bars")
        while self.bars < target_bar:
            self.bars = min(self.bars + self.expansion_chunk, self.max_bars)
        return self.bars

    def ensure_visible_bar(self, bar: int) -> int:
        target_bar = max(int(bar), 1)
        if target_bar > self.max_bars:
            raise ValueError("bar exceeds max timeline bars")
        if target_bar > self.bars:
            return self.expand_to_bar(target_bar)
        if (
            self.bars < self.max_bars
            and self.expand_threshold_bars > 0
            and target_bar >= (self.bars - self.expand_threshold_bars + 1)
        ):
            return self.expand_to_bar(min(target_bar + self.expansion_chunk, self.max_bars))
        return self.bars

    def refresh_content_end_bar(self) -> int:
        self._recompute_content_end_bar()
        return self.content_end_bar

    def _recompute_content_end_bar(self) -> None:
        self.content_end_bar = max((clip.end_bar for clip in self.clips.values()), default=1)

    def _default_track_color(self, index: int) -> str:
        palette = DEFAULT_TRACK_COLORS
        return palette[index % len(palette)]
