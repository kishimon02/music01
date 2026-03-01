"""Rule-based composition suggestion generator."""

from __future__ import annotations

from dataclasses import dataclass

from music_create.composition.models import (
    GM_DRUM_NOTES,
    KEY_OFFSETS,
    SCALE_INTERVALS,
    ComposeRequest,
    ComposeSuggestion,
    MidiClipDraft,
    MidiNoteEvent,
)
from music_create.composition.quantize import TICKS_PER_BAR_4_4, TICKS_PER_BEAT, quantize_note

_ROMAN_PROGRESSION: dict[str, tuple[int, ...]] = {
    "pop_major": (0, 4, 5, 3),  # I V vi IV
    "pop_minor": (0, 5, 3, 4),  # i VI iv v
    "rock_major": (0, 3, 4, 0),  # I IV V I
    "rock_minor": (0, 3, 4, 0),  # i iv v i
    "hiphop_major": (0, 5, 1, 4),  # I vi ii V
    "hiphop_minor": (0, 4, 5, 3),  # i v VI iv
    "edm_major": (0, 4, 5, 4),  # I V vi V
    "edm_minor": (0, 5, 3, 5),  # i VI iv VI
    "ballad_major": (0, 5, 3, 4),  # I vi IV V
    "ballad_minor": (0, 4, 5, 3),  # i v VI iv
}


@dataclass(frozen=True, slots=True)
class _Candidate:
    score: float
    reason: str
    clip: MidiClipDraft


def generate_rule_suggestions(request: ComposeRequest) -> list[ComposeSuggestion]:
    request.validate()
    clip = _generate_clip(request)
    # Keep top-3 deterministic variants by velocity/offset flavor.
    candidates = [
        _Candidate(score=0.88, reason="rule: base pattern", clip=clip),
        _Candidate(score=0.84, reason="rule: soft velocity variation", clip=_velocity_variant(clip, -10)),
        _Candidate(score=0.81, reason="rule: accent variation", clip=_velocity_variant(clip, 8)),
    ]
    return [
        ComposeSuggestion.new(
            request=request,
            score=item.score,
            source="rule-based",
            reason=item.reason,
            clips=[item.clip],
        )
        for item in candidates
    ]


def _generate_clip(request: ComposeRequest) -> MidiClipDraft:
    if request.part == "chord":
        notes = _build_chord_notes(request)
        name = f"Chord {request.key} {request.scale}"
        is_drum = False
        channel = 0
    elif request.part == "melody":
        notes = _build_melody_notes(request)
        name = f"Melody {request.key} {request.scale}"
        is_drum = False
        channel = 0
    else:
        notes = _build_drum_notes(request)
        name = f"Drum {request.style}"
        is_drum = True
        channel = 9
        # Ensure drum channel for all drum notes.
        for note in notes:
            note.channel = channel

    clip = MidiClipDraft(
        name=name,
        bars=request.bars,
        grid=request.grid,
        notes=notes,
        program=request.program if not is_drum else None,
        is_drum=is_drum,
    )
    clip.validate()
    return clip


def _build_chord_notes(request: ComposeRequest) -> list[MidiNoteEvent]:
    scale = SCALE_INTERVALS[request.scale]
    key_offset = KEY_OFFSETS[request.key]
    progression_key = f"{request.style}_{request.scale}"
    degrees = _ROMAN_PROGRESSION.get(progression_key, _ROMAN_PROGRESSION[f"pop_{request.scale}"])

    notes: list[MidiNoteEvent] = []
    for bar in range(request.bars):
        degree = degrees[bar % len(degrees)]
        root = 48 + key_offset + scale[degree]
        chord_pitches = [root, root + 4 if request.scale == "major" else root + 3, root + 7]
        start_tick = bar * TICKS_PER_BAR_4_4
        length_tick = TICKS_PER_BAR_4_4
        q_start, q_len = quantize_note(start_tick, length_tick, request.grid)
        for pitch in chord_pitches:
            notes.append(
                MidiNoteEvent(
                    start_tick=q_start,
                    length_tick=q_len,
                    pitch=pitch,
                    velocity=88,
                    channel=0,
                )
            )
    return notes


def _build_melody_notes(request: ComposeRequest) -> list[MidiNoteEvent]:
    scale = SCALE_INTERVALS[request.scale]
    key_offset = KEY_OFFSETS[request.key]
    melody_scale = [60 + key_offset + interval for interval in scale]
    notes: list[MidiNoteEvent] = []

    steps_per_bar = 8  # eighth-note phrases before quantize.
    base_len = int(TICKS_PER_BAR_4_4 / steps_per_bar)
    for bar in range(request.bars):
        for step in range(steps_per_bar):
            idx = (bar * steps_per_bar + step) % len(melody_scale)
            start_tick = bar * TICKS_PER_BAR_4_4 + (step * base_len)
            q_start, q_len = quantize_note(start_tick, base_len, request.grid)
            notes.append(
                MidiNoteEvent(
                    start_tick=q_start,
                    length_tick=q_len,
                    pitch=melody_scale[idx],
                    velocity=96 if step % 4 == 0 else 84,
                    channel=0,
                )
            )
    return notes


def _build_drum_notes(request: ComposeRequest) -> list[MidiNoteEvent]:
    notes: list[MidiNoteEvent] = []
    beat_len = TICKS_PER_BEAT
    hi_len = beat_len // 2
    for bar in range(request.bars):
        bar_start = bar * TICKS_PER_BAR_4_4
        # Kick on 1 and 3.
        for beat in (0, 2):
            start_tick = bar_start + beat * beat_len
            q_start, q_len = quantize_note(start_tick, beat_len // 2, request.grid)
            notes.append(
                MidiNoteEvent(
                    start_tick=q_start,
                    length_tick=q_len,
                    pitch=GM_DRUM_NOTES["kick"],
                    velocity=112,
                    channel=9,
                )
            )
        # Snare on 2 and 4.
        for beat in (1, 3):
            start_tick = bar_start + beat * beat_len
            q_start, q_len = quantize_note(start_tick, beat_len // 2, request.grid)
            notes.append(
                MidiNoteEvent(
                    start_tick=q_start,
                    length_tick=q_len,
                    pitch=GM_DRUM_NOTES["snare"],
                    velocity=104,
                    channel=9,
                )
            )
        # Hi-hat 8th base.
        for sub in range(8):
            start_tick = bar_start + sub * hi_len
            q_start, q_len = quantize_note(start_tick, hi_len // 2, request.grid)
            notes.append(
                MidiNoteEvent(
                    start_tick=q_start,
                    length_tick=q_len,
                    pitch=GM_DRUM_NOTES["closed_hihat"],
                    velocity=72 if sub % 2 == 0 else 64,
                    channel=9,
                )
            )
    return notes


def _velocity_variant(clip: MidiClipDraft, delta: int) -> MidiClipDraft:
    copied: list[MidiNoteEvent] = []
    for note in clip.notes:
        velocity = min(max(note.velocity + delta, 1), 127)
        copied.append(
            MidiNoteEvent(
                start_tick=note.start_tick,
                length_tick=note.length_tick,
                pitch=note.pitch,
                velocity=velocity,
                channel=note.channel,
            )
        )
    return MidiClipDraft(
        name=clip.name,
        bars=clip.bars,
        grid=clip.grid,
        notes=copied,
        program=clip.program,
        is_drum=clip.is_drum,
        ticks_per_beat=clip.ticks_per_beat,
    )

