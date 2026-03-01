from pathlib import Path

from music_create.composition.models import MidiClipDraft, MidiNoteEvent
from music_create.composition.synth import render_clip_to_wav


def _clip(program: int) -> MidiClipDraft:
    return MidiClipDraft(
        name=f"program-{program}",
        bars=2,
        grid="1/16",
        notes=[
            MidiNoteEvent(start_tick=0, length_tick=960, pitch=60, velocity=100, channel=0),
            MidiNoteEvent(start_tick=960, length_tick=960, pitch=64, velocity=100, channel=0),
            MidiNoteEvent(start_tick=1920, length_tick=960, pitch=67, velocity=100, channel=0),
        ],
        program=program,
        is_drum=False,
    )


def test_instrument_program_changes_rendered_audio(tmp_path: Path) -> None:
    piano = _clip(0)
    lead = _clip(80)

    piano_wav = render_clip_to_wav(piano, tmp_path / "piano.wav")
    lead_wav = render_clip_to_wav(lead, tmp_path / "lead.wav")

    assert piano_wav.exists()
    assert lead_wav.exists()
    assert piano_wav.read_bytes() != lead_wav.read_bytes()
