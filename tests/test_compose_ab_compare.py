from music_create.composition.models import ComposeRequest, ComposeSuggestion, MidiClipDraft, MidiNoteEvent
from music_create.ui.app import _compose_ab_compare_text


def _suggestion(score: float, reason: str, program: int, note_pitch: int) -> ComposeSuggestion:
    request = ComposeRequest(
        track_id="track-1",
        part="melody",
        key="C",
        scale="major",
        bars=4,
        style="pop",
        grid="1/16",
        program=program,
    )
    clip = MidiClipDraft(
        name="clip",
        bars=4,
        grid="1/16",
        notes=[MidiNoteEvent(start_tick=0, length_tick=240, pitch=note_pitch, velocity=90, channel=0)],
        program=program,
        is_drum=False,
    )
    return ComposeSuggestion.new(
        request=request,
        score=score,
        source="rule-based",
        reason=reason,
        clips=[clip],
    )


def test_compose_ab_compare_text_contains_both_candidates() -> None:
    a = _suggestion(score=0.9, reason="A-reason", program=0, note_pitch=60)
    b = _suggestion(score=0.7, reason="B-reason", program=80, note_pitch=64)
    text = _compose_ab_compare_text(a, b)
    assert "A/B比較" in text
    assert "A-reason" in text
    assert "B-reason" in text
    assert "score差" in text
