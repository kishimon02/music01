"""Helpers for switching the UI between bars and clock time displays."""

from __future__ import annotations

import math

DISPLAY_MODE_BARS = "bars"
DISPLAY_MODE_TIME = "time"
DEFAULT_TICKS_PER_BEAT = 960


def seconds_per_bar(tempo_bpm: float, beats_per_bar: float) -> float:
    beats_per_second = float(tempo_bpm) / 60.0
    if beats_per_second <= 0.0:
        return 2.0
    return max(float(beats_per_bar), 1.0) / beats_per_second


def bar_to_seconds(bar: float, tempo_bpm: float, beats_per_bar: float) -> float:
    return max(float(bar) - 1.0, 0.0) * seconds_per_bar(tempo_bpm, beats_per_bar)


def seconds_to_bar(seconds: float, tempo_bpm: float, beats_per_bar: float) -> float:
    return 1.0 + (max(float(seconds), 0.0) / seconds_per_bar(tempo_bpm, beats_per_bar))


def format_transport_position(
    bar: float,
    *,
    display_mode: str,
    tempo_bpm: float,
    beats_per_bar: float,
    ticks_per_beat: int = DEFAULT_TICKS_PER_BEAT,
) -> str:
    if display_mode == DISPLAY_MODE_TIME:
        return format_clock_time(
            bar_to_seconds(bar, tempo_bpm, beats_per_bar),
            always_include_hours=True,
            include_millis=True,
        )
    return format_bar_position(
        bar,
        beats_per_bar=beats_per_bar,
        ticks_per_beat=ticks_per_beat,
    )


def format_bar_position(
    bar: float,
    *,
    beats_per_bar: float,
    ticks_per_beat: int = DEFAULT_TICKS_PER_BEAT,
) -> str:
    safe_beats_per_bar = max(int(round(beats_per_bar)), 1)
    total_beats = max(float(bar) - 1.0, 0.0) * safe_beats_per_bar
    whole_beats = int(math.floor(total_beats))
    fractional_beat = total_beats - whole_beats
    tick = int(round(fractional_beat * ticks_per_beat))
    bar_number = (whole_beats // safe_beats_per_bar) + 1
    beat_number = (whole_beats % safe_beats_per_bar) + 1
    if tick >= ticks_per_beat:
        tick = 0
        beat_number += 1
        if beat_number > safe_beats_per_bar:
            beat_number = 1
            bar_number += 1
    return f"{bar_number:03d}.{beat_number:02d}.{tick:03d}"


def format_ruler_label(
    bar_number: int,
    *,
    display_mode: str,
    tempo_bpm: float,
    beats_per_bar: float,
) -> str:
    if display_mode == DISPLAY_MODE_TIME:
        seconds = bar_to_seconds(float(bar_number), tempo_bpm, beats_per_bar)
        return format_clock_time(
            seconds,
            always_include_hours=seconds >= 3600.0,
            include_millis=False,
        )
    return str(int(bar_number))


def format_clock_time(
    seconds: float,
    *,
    always_include_hours: bool,
    include_millis: bool,
) -> str:
    safe_seconds = max(float(seconds), 0.0)
    total_millis = int(round(safe_seconds * 1000.0))
    total_seconds, millis = divmod(total_millis, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if always_include_hours or hours > 0:
        base = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        base = f"{minutes:02d}:{secs:02d}"
    if include_millis:
        return f"{base}.{millis:03d}"
    return base


def format_clip_range(
    start_bar: int,
    end_bar: int,
    *,
    display_mode: str,
    tempo_bpm: float,
    beats_per_bar: float,
) -> str:
    if display_mode == DISPLAY_MODE_TIME:
        start = format_clock_time(
            bar_to_seconds(float(start_bar), tempo_bpm, beats_per_bar),
            always_include_hours=False,
            include_millis=True,
        )
        end = format_clock_time(
            bar_to_seconds(float(end_bar + 1), tempo_bpm, beats_per_bar),
            always_include_hours=False,
            include_millis=True,
        )
        return f"{start} - {end}"
    return f"bar {start_bar}-{end_bar}"
