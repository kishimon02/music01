import math
import wave
from pathlib import Path

from music_create.audio.mix_render import is_track_processing_active, render_track_preview_wav
from music_create.audio.wav_loader import load_wav_mono_float32
from music_create.mixing.mixer_graph import MixerGraph
from music_create.mixing.models import BuiltinEffectType


def _write_test_wav(path: Path, sample_rate: int = 48_000, duration_sec: float = 0.25) -> None:
    num_frames = int(sample_rate * duration_sec)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for idx in range(num_frames):
            t = idx / sample_rate
            left = int(18000 * math.sin(2 * math.pi * 220 * t))
            right = int(16000 * math.sin(2 * math.pi * 440 * t))
            frames += int(left).to_bytes(2, "little", signed=True)
            frames += int(right).to_bytes(2, "little", signed=True)
        wav.writeframes(bytes(frames))


def test_render_track_preview_copies_original_when_no_processing(tmp_path: Path) -> None:
    graph = MixerGraph()
    track = graph.ensure_track("track-1")
    assert is_track_processing_active(track) is False

    src = tmp_path / "src.wav"
    dst = tmp_path / "dst.wav"
    _write_test_wav(src)
    render_track_preview_wav(src, dst, track)
    assert dst.exists()
    assert src.read_bytes() == dst.read_bytes()


def test_render_track_preview_applies_fx_changes(tmp_path: Path) -> None:
    graph = MixerGraph()
    track = graph.ensure_track("track-1")
    track.fx_chain.effects[BuiltinEffectType.SATURATOR].parameters["mix"] = 0.85
    track.fx_chain.effects[BuiltinEffectType.SATURATOR].parameters["drive"] = 0.7
    assert is_track_processing_active(track) is True

    src = tmp_path / "src_fx.wav"
    dst = tmp_path / "dst_fx.wav"
    _write_test_wav(src)
    render_track_preview_wav(src, dst, track)
    assert dst.exists()
    assert src.read_bytes() != dst.read_bytes()

    src_data = load_wav_mono_float32(src)
    dst_data = load_wav_mono_float32(dst)
    assert len(src_data.samples) == len(dst_data.samples)
    mean_abs_diff = sum(abs(a - b) for a, b in zip(src_data.samples, dst_data.samples)) / len(src_data.samples)
    assert mean_abs_diff > 0.005
