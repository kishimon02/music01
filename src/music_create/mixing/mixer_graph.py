"""Fixed mixer graph shape used for deterministic automation targets."""

from __future__ import annotations

from dataclasses import dataclass, field

from music_create.mixing.fx import default_fx_chain
from music_create.mixing.models import BuiltinFXChainState


@dataclass(slots=True)
class SendState:
    target_bus_id: str
    level_db: float = -12.0
    pre_fader: bool = False


@dataclass(slots=True)
class MixerTrackState:
    track_id: str
    input_gain_db: float = 0.0
    fx_chain: BuiltinFXChainState = field(default_factory=default_fx_chain)
    fader_db: float = 0.0
    pan: float = 0.0
    sends: list[SendState] = field(default_factory=list)


@dataclass(slots=True)
class MixerGraph:
    tracks: dict[str, MixerTrackState] = field(default_factory=dict)

    def ensure_track(self, track_id: str) -> MixerTrackState:
        existing = self.tracks.get(track_id)
        if existing:
            return existing
        track = MixerTrackState(track_id=track_id)
        self.tracks[track_id] = track
        return track
