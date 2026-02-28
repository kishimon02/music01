"""Timeline domain model for DAW-style UI integration."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(slots=True)
class TimelineTrack:
    track_id: str
    name: str


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
    def __init__(self, bars: int = 16) -> None:
        if bars <= 0:
            raise ValueError("bars must be positive")
        self.bars = bars
        self.playhead_bar = 1.0
        self.tracks: dict[str, TimelineTrack] = {}
        self.clips: dict[str, TimelineClip] = {}

    def add_track(self, name: str | None = None) -> TimelineTrack:
        index = len(self.tracks) + 1
        track_id = f"track-{index}"
        track = TimelineTrack(track_id=track_id, name=name or f"Track {index}")
        self.tracks[track_id] = track
        return track

    def add_clip(
        self,
        track_id: str,
        clip_type: str,
        start_bar: int,
        length_bars: int,
        name: str | None = None,
    ) -> TimelineClip:
        if track_id not in self.tracks:
            raise KeyError(f"track '{track_id}' not found")
        if clip_type not in {"midi", "audio"}:
            raise ValueError(f"unsupported clip_type '{clip_type}'")
        if start_bar < 1:
            raise ValueError("start_bar must be >= 1")
        if length_bars <= 0:
            raise ValueError("length_bars must be positive")
        if start_bar + length_bars - 1 > self.bars:
            raise ValueError("clip exceeds timeline bars")

        clip = TimelineClip(
            clip_id=str(uuid4()),
            track_id=track_id,
            name=name or f"{clip_type.upper()} Clip",
            clip_type=clip_type,
            start_bar=start_bar,
            length_bars=length_bars,
        )
        self.clips[clip.clip_id] = clip
        return clip

    def set_playhead_bar(self, bar: float) -> None:
        self.playhead_bar = min(max(bar, 1.0), float(self.bars))

    def tracks_in_order(self) -> list[TimelineTrack]:
        return list(self.tracks.values())

    def clips_for_track(self, track_id: str) -> list[TimelineClip]:
        items = [clip for clip in self.clips.values() if clip.track_id == track_id]
        return sorted(items, key=lambda clip: (clip.start_bar, clip.clip_id))

