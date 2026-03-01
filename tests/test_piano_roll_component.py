from music_create.ui.piano_roll import PianoRollNote, roll_pitch_range


def test_roll_pitch_range_default_when_empty() -> None:
    assert roll_pitch_range([]) == (48, 72)


def test_roll_pitch_range_uses_note_bounds_with_margin() -> None:
    notes = [
        PianoRollNote(start_tick=0, length_tick=240, pitch=60, velocity=100),
        PianoRollNote(start_tick=240, length_tick=240, pitch=72, velocity=100),
    ]
    low, high = roll_pitch_range(notes)
    assert low <= 58
    assert high >= 74
    assert high > low
