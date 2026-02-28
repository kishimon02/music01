import math
import wave
from pathlib import Path

from music_create.audio.repository import WaveformRepository
from music_create.audio.wav_loader import load_wav_mono_float32


def _write_test_wav(path: Path, sample_rate: int = 48000, duration_sec: float = 0.1) -> None:
    num_frames = int(sample_rate * duration_sec)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for idx in range(num_frames):
            t = idx / sample_rate
            left = int(20000 * math.sin(2 * math.pi * 440 * t))
            right = int(15000 * math.sin(2 * math.pi * 880 * t))
            frames += int(left).to_bytes(2, "little", signed=True)
            frames += int(right).to_bytes(2, "little", signed=True)
        wav.writeframes(bytes(frames))


def test_load_wav_mono_float32(tmp_path: Path) -> None:
    wav_path = tmp_path / "test.wav"
    _write_test_wav(wav_path)

    loaded = load_wav_mono_float32(wav_path)
    assert loaded.sample_rate == 48000
    assert loaded.channels == 2
    assert loaded.frame_count > 0
    assert loaded.duration_sec > 0.0
    assert loaded.samples
    assert max(loaded.samples) <= 1.0
    assert min(loaded.samples) >= -1.0


def test_waveform_repository_assigns_track(tmp_path: Path) -> None:
    wav_path = tmp_path / "track.wav"
    _write_test_wav(wav_path, duration_sec=0.2)

    repository = WaveformRepository()
    data = repository.load_track_wav("track-1", wav_path)
    assert data.track_id == "track-1"
    assert data.duration_sec > 0.19
    assert repository.get_samples("track-1")
