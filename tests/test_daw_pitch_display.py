from music_create.ui.app import midi_note_name
from music_create.ui.piano_roll import pitch_axis_labels


def test_midi_note_name_conversion() -> None:
    assert midi_note_name(0) == "C-1"
    assert midi_note_name(60) == "C4"
    assert midi_note_name(61) == "C#4"
    assert midi_note_name(127) == "G9"


def test_pitch_axis_labels_render_top_to_bottom() -> None:
    assert pitch_axis_labels(60, 63) == ["D#4", "D4", "C#4", "C4"]
