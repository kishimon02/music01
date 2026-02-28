"""Deterministic rule-based baseline suggestion generator."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from music_create.mixing.models import BuiltinEffectType, MixProfile, Suggestion, TrackFeatures


def suggest_from_features(track_id: str, profile: MixProfile, features: TrackFeatures) -> list[Suggestion]:
    role = _infer_role(features)
    variants = _build_variants(profile, role, features)
    variants.sort(key=lambda item: item.score, reverse=True)

    suggestions: list[Suggestion] = []
    for candidate in variants[:3]:
        suggestions.append(
            Suggestion(
                suggestion_id=str(uuid4()),
                track_id=track_id,
                profile=profile,
                variant=candidate.variant,
                score=round(candidate.score, 4),
                reason=(
                    f"profile={profile}, role={role}, centroid={features.spectral_centroid_hz:.1f}, "
                    f"transient={features.transient_density:.3f}, lra={features.loudness_range_db:.1f}"
                ),
                param_updates=candidate.param_updates,
            )
        )
    return suggestions


@dataclass(frozen=True, slots=True)
class _Candidate:
    variant: str
    score: float
    param_updates: dict[BuiltinEffectType, dict[str, float]]


def _infer_role(features: TrackFeatures) -> str:
    if features.band_energy_low >= 0.44 and features.spectral_centroid_hz < 900:
        return "bass"
    if features.transient_density > 0.18 and features.crest_factor_db > 8.0:
        return "drums"
    if features.band_energy_high > 0.42 and features.spectral_centroid_hz > 2500:
        return "lead"
    return "harmonic"


def _build_variants(profile: MixProfile, role: str, features: TrackFeatures) -> list[_Candidate]:
    profile_gain = {"clean": 0.05, "punch": 0.08, "warm": 0.06}[profile]
    role_bias = {"bass": 0.09, "drums": 0.1, "lead": 0.07, "harmonic": 0.06}[role]

    gate_threshold = -58.0 if features.dynamic_range_db > 19.0 else -45.0
    if role == "drums":
        gate_threshold -= 4.0

    base_ratio = 2.4 if profile == "clean" else (4.2 if profile == "punch" else 3.2)
    base_eq_high = 1.8 if profile == "clean" else (1.1 if profile == "punch" else -0.6)
    if role == "bass":
        base_eq_high -= 1.2
    if role == "lead":
        base_eq_high += 0.8

    base_sat = 0.08 if profile == "clean" else (0.26 if profile == "punch" else 0.34)
    if role == "drums":
        base_sat += 0.08

    transient_push = min(max((features.transient_density - 0.08) * 1.8, 0.0), 0.18)
    lra_push = min(max((features.loudness_range_db - 7.0) * 0.012, 0.0), 0.1)

    return [
        _Candidate(
            variant="balanced",
            score=0.78 + profile_gain + role_bias + lra_push,
            param_updates={
                BuiltinEffectType.EQ: {"high_gain_db": base_eq_high},
                BuiltinEffectType.COMPRESSOR: {"ratio": base_ratio, "threshold_db": -20.0 + transient_push * -10},
                BuiltinEffectType.GATE: {"threshold_db": gate_threshold},
                BuiltinEffectType.SATURATOR: {"mix": base_sat},
            },
        ),
        _Candidate(
            variant="tight",
            score=0.75 + profile_gain + transient_push + role_bias * 0.9,
            param_updates={
                BuiltinEffectType.EQ: {"high_gain_db": base_eq_high - 0.5},
                BuiltinEffectType.COMPRESSOR: {"ratio": base_ratio + 0.8, "threshold_db": -23.0},
                BuiltinEffectType.GATE: {"threshold_db": gate_threshold - 3.0},
                BuiltinEffectType.SATURATOR: {"mix": min(base_sat + 0.08, 0.9)},
            },
        ),
        _Candidate(
            variant="wide",
            score=0.72 + profile_gain + (features.band_energy_high * 0.09),
            param_updates={
                BuiltinEffectType.EQ: {"high_gain_db": base_eq_high + 0.7},
                BuiltinEffectType.COMPRESSOR: {"ratio": max(base_ratio - 0.7, 1.2), "threshold_db": -18.0},
                BuiltinEffectType.GATE: {"threshold_db": gate_threshold + 4.0},
                BuiltinEffectType.SATURATOR: {"mix": max(base_sat - 0.06, 0.02)},
            },
        ),
    ]
