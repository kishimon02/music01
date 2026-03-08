import pytest

from music_create.ui.timeline import TimelineState


def test_add_track_and_clip() -> None:
    timeline = TimelineState(bars=16)
    track = timeline.add_track("Drums")

    clip = timeline.add_clip(
        track_id=track.track_id,
        clip_type="audio",
        start_bar=1,
        length_bars=8,
        name="Drum Loop",
    )

    assert clip.end_bar == 8
    assert timeline.clips_for_track(track.track_id)[0].name == "Drum Loop"


def test_playhead_is_clamped_to_timeline_range() -> None:
    timeline = TimelineState(bars=16)
    timeline.set_playhead_bar(24.0)
    assert timeline.playhead_bar == 24.0
    assert timeline.bars == 80

    timeline.set_playhead_bar(0.0)
    assert timeline.playhead_bar == 1.0


def test_timeline_auto_expands_when_clip_exceeds_current_view() -> None:
    timeline = TimelineState(bars=64, max_bars=1000, expansion_chunk=64)
    track = timeline.add_track("Long Form")

    clip = timeline.add_clip(
        track_id=track.track_id,
        clip_type="audio",
        start_bar=96,
        length_bars=8,
        name="Bridge",
    )

    assert clip.end_bar == 103
    assert timeline.bars == 128
    assert timeline.content_end_bar == 103


def test_timeline_expansion_stops_at_max_bars() -> None:
    timeline = TimelineState(bars=64, max_bars=128, expansion_chunk=32)
    track = timeline.add_track("Edge")

    with pytest.raises(ValueError):
        timeline.add_clip(
            track_id=track.track_id,
            clip_type="midi",
            start_bar=124,
            length_bars=8,
            name="Too Long",
        )


def test_playhead_near_timeline_end_expands_visible_range() -> None:
    timeline = TimelineState(bars=64, max_bars=160, expansion_chunk=32, expand_threshold_bars=8)
    timeline.set_playhead_bar(60.0)

    assert timeline.playhead_bar == 60.0
    assert timeline.bars == 96


def test_add_track_stores_instrument_metadata() -> None:
    timeline = TimelineState(bars=16)

    track = timeline.add_track(
        "Bell 1",
        instrument_name="Bell",
        program=10,
        is_drum=False,
        color="#123456",
    )

    assert track.instrument_name == "Bell"
    assert track.program == 10
    assert track.is_drum is False
    assert track.color == "#123456"
