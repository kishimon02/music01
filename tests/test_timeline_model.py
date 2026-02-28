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
    assert timeline.playhead_bar == 16.0

    timeline.set_playhead_bar(0.0)
    assert timeline.playhead_bar == 1.0

