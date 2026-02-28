"""Deterministic rule-based baseline suggestion generator."""

from __future__ import annotations

from uuid import uuid4

from music_create.mixing.models import BuiltinEffectType, MixProfile, Suggestion, TrackFeatures


def suggest_from_features(track_id: str, profile: MixProfile, features: TrackFeatures) -> list[Suggestion]:
    if profile == "clean":
        eq_high = 2.0 if features.spectral_centroid_hz < 1200 else 0.5
        comp_ratio = 2.5
        sat_mix = 0.1
    elif profile == "punch":
        eq_high = 1.0
        comp_ratio = 4.0
        sat_mix = 0.25
    else:  # warm
        eq_high = -0.8
        comp_ratio = 3.0
        sat_mix = 0.35

    gate_threshold = -55.0 if features.dynamic_range_db > 18.0 else -45.0

    candidate = Suggestion(
        suggestion_id=str(uuid4()),
        track_id=track_id,
        profile=profile,
        reason=(
            f"profile={profile}, centroid={features.spectral_centroid_hz:.1f}, "
            f"dyn={features.dynamic_range_db:.1f}"
        ),
        param_updates={
            BuiltinEffectType.EQ: {"high_gain_db": eq_high},
            BuiltinEffectType.COMPRESSOR: {"ratio": comp_ratio, "threshold_db": -20.0},
            BuiltinEffectType.GATE: {"threshold_db": gate_threshold},
            BuiltinEffectType.SATURATOR: {"mix": sat_mix},
        },
    )
    return [candidate]
