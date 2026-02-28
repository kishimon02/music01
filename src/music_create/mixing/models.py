"""Core mixing models for MVP and post-MVP automation boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Literal
from uuid import uuid4


class BuiltinEffectType(str, Enum):
    EQ = "eq"
    COMPRESSOR = "compressor"
    GATE = "gate"
    SATURATOR = "saturator"


class AnalysisMode(str, Enum):
    QUICK = "quick"
    FULL = "full"


MixProfile = Literal["clean", "punch", "warm"]


@dataclass(slots=True)
class BuiltinFXState:
    effect_type: BuiltinEffectType
    parameters: dict[str, float]


@dataclass(slots=True)
class BuiltinFXChainState:
    effects: dict[BuiltinEffectType, BuiltinFXState]

    def clone(self) -> BuiltinFXChainState:
        return BuiltinFXChainState(
            effects={
                fx_type: BuiltinFXState(
                    effect_type=fx_state.effect_type,
                    parameters=dict(fx_state.parameters),
                )
                for fx_type, fx_state in self.effects.items()
            }
        )


@dataclass(slots=True)
class TrackFeatures:
    lufs: float
    peak_dbfs: float
    rms_dbfs: float
    crest_factor_db: float
    spectral_centroid_hz: float
    band_energy_low: float
    band_energy_mid: float
    band_energy_high: float
    dynamic_range_db: float
    loudness_range_db: float
    transient_density: float
    zero_crossing_rate: float


@dataclass(slots=True)
class AnalysisSnapshot:
    analysis_id: str
    mode: AnalysisMode
    created_at: datetime
    track_features: dict[str, TrackFeatures]

    @staticmethod
    def new(mode: AnalysisMode, track_features: dict[str, TrackFeatures]) -> AnalysisSnapshot:
        return AnalysisSnapshot(
            analysis_id=str(uuid4()),
            mode=mode,
            created_at=datetime.now(UTC),
            track_features=track_features,
        )


@dataclass(slots=True)
class Suggestion:
    suggestion_id: str
    track_id: str
    profile: MixProfile
    variant: str
    score: float
    reason: str
    param_updates: dict[BuiltinEffectType, dict[str, float]]


@dataclass(slots=True)
class SuggestionCommand:
    command_id: str
    track_id: str
    suggestion_id: str
    created_at: datetime
    before_chain: BuiltinFXChainState
    after_chain: BuiltinFXChainState
    applied: bool = field(default=False)

    @staticmethod
    def new(
        track_id: str,
        suggestion_id: str,
        before_chain: BuiltinFXChainState,
        after_chain: BuiltinFXChainState,
    ) -> SuggestionCommand:
        return SuggestionCommand(
            command_id=str(uuid4()),
            track_id=track_id,
            suggestion_id=suggestion_id,
            created_at=datetime.now(UTC),
            before_chain=before_chain,
            after_chain=after_chain,
            applied=False,
        )
