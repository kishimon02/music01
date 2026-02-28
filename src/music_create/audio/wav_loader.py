"""WAV loading helpers for real waveform-based analysis."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class LoadedWaveform:
    sample_rate: int
    channels: int
    frame_count: int
    samples: list[float]

    @property
    def duration_sec(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return self.frame_count / self.sample_rate


def load_wav_mono_float32(path: str | Path) -> LoadedWaveform:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(str(file_path))

    with wave.open(str(file_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)

    if channels <= 0:
        raise ValueError("invalid channel count in wav file")
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError(f"unsupported sample width: {sample_width}")

    samples = _decode_mono_float_samples(raw, channels, sample_width)
    return LoadedWaveform(
        sample_rate=sample_rate,
        channels=channels,
        frame_count=frame_count,
        samples=samples,
    )


def _decode_mono_float_samples(raw: bytes, channels: int, sample_width: int) -> list[float]:
    frame_size = channels * sample_width
    if frame_size <= 0:
        return []
    samples: list[float] = []
    for frame_start in range(0, len(raw), frame_size):
        frame = raw[frame_start : frame_start + frame_size]
        if len(frame) < frame_size:
            break
        total = 0.0
        for ch in range(channels):
            offset = ch * sample_width
            chunk = frame[offset : offset + sample_width]
            total += _decode_one_sample(chunk, sample_width)
        samples.append(max(min(total / channels, 1.0), -1.0))
    return samples


def _decode_one_sample(chunk: bytes, sample_width: int) -> float:
    if sample_width == 1:
        return (chunk[0] - 128) / 128.0
    if sample_width == 2:
        value = int.from_bytes(chunk, "little", signed=True)
        return value / 32768.0
    if sample_width == 3:
        sign = b"\xff" if chunk[2] & 0x80 else b"\x00"
        value = int.from_bytes(chunk + sign, "little", signed=True)
        return value / 8388608.0
    value = int.from_bytes(chunk, "little", signed=True)
    return value / 2147483648.0
