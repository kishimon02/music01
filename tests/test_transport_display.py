from music_create.ui.transport_display import (
    DISPLAY_MODE_BARS,
    DISPLAY_MODE_TIME,
    format_clip_range,
    format_ruler_label,
    format_transport_position,
)


def test_transport_position_formats_bars_with_bar_beat_tick() -> None:
    assert format_transport_position(
        1.0,
        display_mode=DISPLAY_MODE_BARS,
        tempo_bpm=120.0,
        beats_per_bar=4.0,
    ) == "001.01.000"
    assert format_transport_position(
        3.5,
        display_mode=DISPLAY_MODE_BARS,
        tempo_bpm=120.0,
        beats_per_bar=4.0,
    ) == "003.03.000"


def test_transport_position_formats_time_with_millis() -> None:
    assert format_transport_position(
        5.0,
        display_mode=DISPLAY_MODE_TIME,
        tempo_bpm=120.0,
        beats_per_bar=4.0,
    ) == "00:00:08.000"


def test_ruler_label_switches_between_bars_and_clock() -> None:
    assert format_ruler_label(
        9,
        display_mode=DISPLAY_MODE_BARS,
        tempo_bpm=120.0,
        beats_per_bar=4.0,
    ) == "9"
    assert format_ruler_label(
        65,
        display_mode=DISPLAY_MODE_TIME,
        tempo_bpm=120.0,
        beats_per_bar=4.0,
    ) == "02:08"


def test_clip_range_switches_between_bars_and_clock() -> None:
    assert format_clip_range(
        1,
        4,
        display_mode=DISPLAY_MODE_BARS,
        tempo_bpm=120.0,
        beats_per_bar=4.0,
    ) == "bar 1-4"
    assert format_clip_range(
        1,
        4,
        display_mode=DISPLAY_MODE_TIME,
        tempo_bpm=120.0,
        beats_per_bar=4.0,
    ) == "00:00.000 - 00:08.000"
