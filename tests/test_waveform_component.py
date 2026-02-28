from music_create.ui.waveform import build_waveform_envelope


def test_build_waveform_envelope_returns_requested_bin_count() -> None:
    samples = [-1.0, -0.2, 0.3, 0.8, -0.4, 0.1, 0.9]
    envelope = build_waveform_envelope(samples, bins=4)
    assert len(envelope) == 4
    for low, high in envelope:
        assert -1.0 <= low <= 1.0
        assert -1.0 <= high <= 1.0
        assert low <= high


def test_build_waveform_envelope_handles_empty_samples() -> None:
    envelope = build_waveform_envelope([], bins=5)
    assert envelope == [(0.0, 0.0)] * 5
