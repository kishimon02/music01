"""Track to waveform mapping for analysis and playback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from music_create.audio.wav_loader import LoadedWaveform, load_wav_mono_float32


@dataclass(slots=True)
class WaveformTrackData:
    track_id: str
    path: Path
    sample_rate: int
    duration_sec: float
    samples: list[float]


class WaveformRepository:
    def __init__(self) -> None:
        self._items: dict[str, WaveformTrackData] = {}

    def load_track_wav(self, track_id: str, path: str | Path) -> WaveformTrackData:
        loaded: LoadedWaveform = load_wav_mono_float32(path)
        item = WaveformTrackData(
            track_id=track_id,
            path=Path(path),
            sample_rate=loaded.sample_rate,
            duration_sec=loaded.duration_sec,
            samples=loaded.samples,
        )
        self._items[track_id] = item
        return item

    def get_samples(self, track_id: str) -> list[float] | None:
        item = self._items.get(track_id)
        if item is None:
            return None
        return item.samples

    def get_item(self, track_id: str) -> WaveformTrackData | None:
        return self._items.get(track_id)

