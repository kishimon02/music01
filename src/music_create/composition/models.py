"""Composition domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

Key = Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
Scale = Literal["major", "minor"]
Style = Literal["pop", "rock", "hiphop", "edm", "ballad"]
Part = Literal["chord", "melody", "drum"]
Grid = Literal["1", "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T", "1/16", "1/16T", "1/32", "1/32T", "1/64"]
ComposeMode = Literal["rule-based", "llm-based"]

SUPPORTED_GRIDS: tuple[Grid, ...] = (
    "1",
    "1/2",
    "1/2T",
    "1/4",
    "1/4T",
    "1/8",
    "1/8T",
    "1/16",
    "1/16T",
    "1/32",
    "1/32T",
    "1/64",
)

SUPPORTED_PARTS: tuple[Part, ...] = ("chord", "melody", "drum")
SUPPORTED_STYLES: tuple[Style, ...] = ("pop", "rock", "hiphop", "edm", "ballad")

KEY_OFFSETS: dict[Key, int] = {
    "C": 0,
    "C#": 1,
    "D": 2,
    "D#": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "G": 7,
    "G#": 8,
    "A": 9,
    "A#": 10,
    "B": 11,
}

SCALE_INTERVALS: dict[Scale, tuple[int, ...]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
}

GM_DRUM_NOTES: dict[str, int] = {
    "kick": 36,
    "snare": 38,
    "closed_hihat": 42,
    "open_hihat": 46,
    "clap": 39,
    "crash": 49,
}


def is_valid_grid(value: str) -> bool:
    return value in SUPPORTED_GRIDS


@dataclass(slots=True)
class ComposeRequest:
    track_id: str
    part: Part
    key: Key
    scale: Scale
    bars: int
    style: Style
    grid: Grid = "1/16"
    program: int | None = None

    def validate(self) -> None:
        if self.part not in SUPPORTED_PARTS:
            raise ValueError(f"Unsupported part '{self.part}'")
        if self.style not in SUPPORTED_STYLES:
            raise ValueError(f"Unsupported style '{self.style}'")
        if self.grid not in SUPPORTED_GRIDS:
            raise ValueError(f"Unsupported grid '{self.grid}'")
        if self.bars <= 0:
            raise ValueError("bars must be positive")
        if self.bars > 32:
            raise ValueError("bars must be <= 32")
        if self.program is not None and not (0 <= self.program <= 127):
            raise ValueError("program must be in range [0,127]")


@dataclass(slots=True)
class MidiNoteEvent:
    start_tick: int
    length_tick: int
    pitch: int
    velocity: int
    channel: int

    def validate(self) -> None:
        if self.start_tick < 0:
            raise ValueError("start_tick must be >= 0")
        if self.length_tick <= 0:
            raise ValueError("length_tick must be > 0")
        if not (0 <= self.pitch <= 127):
            raise ValueError("pitch must be in range [0,127]")
        if not (1 <= self.velocity <= 127):
            raise ValueError("velocity must be in range [1,127]")
        if not (0 <= self.channel <= 15):
            raise ValueError("channel must be in range [0,15]")


@dataclass(slots=True)
class MidiClipDraft:
    name: str
    bars: int
    grid: Grid
    notes: list[MidiNoteEvent]
    program: int | None
    is_drum: bool
    ticks_per_beat: int = 960

    def validate(self) -> None:
        if self.bars <= 0:
            raise ValueError("bars must be positive")
        if self.grid not in SUPPORTED_GRIDS:
            raise ValueError(f"Unsupported grid '{self.grid}'")
        for note in self.notes:
            note.validate()


@dataclass(slots=True)
class ComposeSuggestion:
    suggestion_id: str
    request: ComposeRequest
    score: float
    source: Literal["rule-based", "llm-based", "rule-based-fallback"]
    reason: str
    clips: list[MidiClipDraft]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def new(
        request: ComposeRequest,
        score: float,
        source: Literal["rule-based", "llm-based", "rule-based-fallback"],
        reason: str,
        clips: list[MidiClipDraft],
    ) -> ComposeSuggestion:
        return ComposeSuggestion(
            suggestion_id=str(uuid4()),
            request=request,
            score=score,
            source=source,
            reason=reason,
            clips=clips,
        )


@dataclass(slots=True)
class ComposeCommand:
    command_id: str
    suggestion_id: str
    track_id: str
    created_clip_ids: list[str]
    created_at: datetime
    applied: bool = True

    @staticmethod
    def new(suggestion_id: str, track_id: str, created_clip_ids: list[str]) -> ComposeCommand:
        return ComposeCommand(
            command_id=str(uuid4()),
            suggestion_id=suggestion_id,
            track_id=track_id,
            created_clip_ids=list(created_clip_ids),
            created_at=datetime.now(UTC),
            applied=True,
        )

