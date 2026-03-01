from music_create.ui.app import midi_note_name, pitch_class_guide_text


def test_midi_note_name_conversion() -> None:
    assert midi_note_name(0) == "C-1"
    assert midi_note_name(60) == "C4"
    assert midi_note_name(61) == "C#4"
    assert midi_note_name(127) == "G9"


def test_pitch_class_guide_text() -> None:
    assert pitch_class_guide_text() == "C C# D D# E F F# G G# A A# B"
