"""Built-in FX specs and capability registry."""

from __future__ import annotations

from dataclasses import dataclass

from music_create.mixing.models import BuiltinEffectType, BuiltinFXChainState, BuiltinFXState


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    param_id: str
    default: float
    minimum: float
    maximum: float


@dataclass(frozen=True, slots=True)
class EffectSpec:
    effect_type: BuiltinEffectType
    parameters: tuple[ParameterSpec, ...]


@dataclass(frozen=True, slots=True)
class FXCapabilityRegistry:
    builtin_only: bool = True


EFFECT_SPECS: dict[BuiltinEffectType, EffectSpec] = {
    BuiltinEffectType.EQ: EffectSpec(
        effect_type=BuiltinEffectType.EQ,
        parameters=(
            ParameterSpec("low_gain_db", 0.0, -18.0, 18.0),
            ParameterSpec("mid_gain_db", 0.0, -18.0, 18.0),
            ParameterSpec("high_gain_db", 0.0, -18.0, 18.0),
            ParameterSpec("low_freq_hz", 120.0, 20.0, 400.0),
            ParameterSpec("high_freq_hz", 5000.0, 1500.0, 12000.0),
        ),
    ),
    BuiltinEffectType.COMPRESSOR: EffectSpec(
        effect_type=BuiltinEffectType.COMPRESSOR,
        parameters=(
            ParameterSpec("threshold_db", -18.0, -60.0, 0.0),
            ParameterSpec("ratio", 3.0, 1.0, 20.0),
            ParameterSpec("attack_ms", 12.0, 0.1, 100.0),
            ParameterSpec("release_ms", 120.0, 5.0, 1000.0),
            ParameterSpec("makeup_db", 0.0, 0.0, 24.0),
        ),
    ),
    BuiltinEffectType.GATE: EffectSpec(
        effect_type=BuiltinEffectType.GATE,
        parameters=(
            ParameterSpec("threshold_db", -40.0, -80.0, 0.0),
            ParameterSpec("attack_ms", 2.0, 0.1, 50.0),
            ParameterSpec("release_ms", 120.0, 5.0, 500.0),
        ),
    ),
    BuiltinEffectType.SATURATOR: EffectSpec(
        effect_type=BuiltinEffectType.SATURATOR,
        parameters=(
            ParameterSpec("drive", 0.0, 0.0, 1.0),
            ParameterSpec("mix", 0.0, 0.0, 1.0),
        ),
    ),
}


def default_fx_chain() -> BuiltinFXChainState:
    effects: dict[BuiltinEffectType, BuiltinFXState] = {}
    for effect_type, spec in EFFECT_SPECS.items():
        effects[effect_type] = BuiltinFXState(
            effect_type=effect_type,
            parameters={param.param_id: param.default for param in spec.parameters},
        )
    return BuiltinFXChainState(effects=effects)


def clamp_param(effect_type: BuiltinEffectType, param_id: str, value: float) -> float:
    spec = EFFECT_SPECS[effect_type]
    for param in spec.parameters:
        if param.param_id == param_id:
            return min(max(value, param.minimum), param.maximum)
    raise KeyError(f"Unknown parameter '{param_id}' for effect '{effect_type.value}'")
