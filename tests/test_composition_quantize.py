from music_create.composition.models import SUPPORTED_GRIDS
from music_create.composition.quantize import GRID_STEP_TICKS, grid_to_step_ticks, quantize_note


EXPECTED_GRID_STEP_TICKS = {
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


def test_grid_step_ticks_table_matches_spec() -> None:
    assert tuple(EXPECTED_GRID_STEP_TICKS.keys()) == SUPPORTED_GRIDS
    assert GRID_STEP_TICKS == EXPECTED_GRID_STEP_TICKS
    for grid, expected in EXPECTED_GRID_STEP_TICKS.items():
        assert grid_to_step_ticks(grid) == expected


def test_quantize_note_rounds_to_grid_step_units() -> None:
    # start_tick=137, len_tick=221 rounds around each grid step threshold.
    for grid, step in EXPECTED_GRID_STEP_TICKS.items():
        q_start, q_len = quantize_note(start_tick=137, len_tick=221, grid=grid)
        assert q_start % step == 0
        assert q_len % step == 0
        assert q_start >= 0
        assert q_len >= step


def test_triplet_quantize_note_cases() -> None:
    triplet_cases = [
        ("1/2T", 700, 900, 1280, 1280),
        ("1/4T", 319, 319, 0, 640),
        ("1/8T", 500, 150, 640, 320),
        ("1/16T", 95, 95, 160, 160),
        ("1/32T", 41, 39, 80, 80),
    ]
    for grid, start_tick, len_tick, expected_start, expected_len in triplet_cases:
        q_start, q_len = quantize_note(start_tick=start_tick, len_tick=len_tick, grid=grid)
        assert q_start == expected_start
        assert q_len == expected_len

