"""Quantization utilities for composition suggestion outputs."""

from __future__ import annotations

from music_create.composition.models import Grid, SUPPORTED_GRIDS

TICKS_PER_BEAT = 960
TICKS_PER_BAR_4_4 = TICKS_PER_BEAT * 4

GRID_STEP_TICKS: dict[Grid, int] = {
    "1": 3840,
    "1/2": 1920,
    "1/2T": 1280,
    "1/4": 960,
    "1/4T": 640,
    "1/8": 480,
    "1/8T": 320,
    "1/16": 240,
    "1/16T": 160,
    "1/32": 120,
    "1/32T": 80,
    "1/64": 60,
}


def normalize_grid(grid: str) -> Grid:
    if grid in SUPPORTED_GRIDS:
        return grid
    raise ValueError(f"Unsupported grid '{grid}'")


def grid_to_step_ticks(grid: Grid) -> int:
    return GRID_STEP_TICKS[grid]


def quantize_tick(tick: int, grid: Grid) -> int:
    step = grid_to_step_ticks(grid)
    if tick <= 0:
        return 0
    remainder = tick % step
    lower = tick - remainder
    upper = lower + step
    if remainder < (step / 2):
        return lower
    return upper


def quantize_note(start_tick: int, len_tick: int, grid: Grid) -> tuple[int, int]:
    step = grid_to_step_ticks(grid)
    start = max(0, quantize_tick(start_tick, grid))
    length = max(step, quantize_tick(len_tick, grid))
    return start, length

