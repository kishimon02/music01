"""Suggestion engine abstraction with rule/LLM switch and fallback hooks."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from music_create.mixing.models import BuiltinEffectType, MixProfile, Suggestion, TrackFeatures
from music_create.mixing.suggestions import suggest_from_features

SuggestionEngineMode = Literal["rule-based", "llm-based"]

_HTTPTransport = Callable[[str, dict[str, object], dict[str, str], float], dict[str, object]]


class SuggestionEngineError(RuntimeError):
    """Raised when a suggestion engine cannot produce candidates."""


def normalize_suggestion_engine(mode: str | None) -> SuggestionEngineMode:
    if mode is None:
        return "rule-based"
    normalized = mode.strip().lower()
    if normalized in {"rule", "rule-based", "rule_based"}:
        return "rule-based"
    if normalized in {"llm", "llm-based", "llm_based"}:
        return "llm-based"
    raise ValueError(f"Unsupported suggestion engine '{mode}'")


class RuleBasedSuggestionEngine:
    mode: SuggestionEngineMode = "rule-based"

    def generate(self, track_id: str, profile: MixProfile, features: TrackFeatures) -> list[Suggestion]:
        return suggest_from_features(track_id=track_id, profile=profile, features=features)


@dataclass(slots=True)
class LLMSuggestionEngine:
    endpoint: str = ""
    api_key: str = ""
    timeout_sec: float = 6.0
    transport: _HTTPTransport | None = None
    model: str = ""

    @staticmethod
    def from_env() -> LLMSuggestionEngine:
        endpoint = os.getenv("MUSIC_CREATE_LLM_ENDPOINT", "").strip()
        api_key = os.getenv("MUSIC_CREATE_LLM_API_KEY", "").strip()
        model = os.getenv("MUSIC_CREATE_LLM_MODEL", "").strip()
        timeout_raw = os.getenv("MUSIC_CREATE_LLM_TIMEOUT_SEC", "6.0").strip()
        try:
            timeout_sec = float(timeout_raw)
        except ValueError:
            timeout_sec = 6.0
        return LLMSuggestionEngine(
            endpoint=endpoint,
            api_key=api_key,
            timeout_sec=max(timeout_sec, 0.1),
            model=model,
        )

    def generate(self, track_id: str, profile: MixProfile, features: TrackFeatures) -> list[Suggestion]:
        if not self.endpoint:
            raise SuggestionEngineError("MUSIC_CREATE_LLM_ENDPOINT is not configured")

        payload = {
            "track_id": track_id,
            "profile": profile,
            "features": _feature_payload(features),
            "model": self.model or None,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        transport = self.transport or _default_http_transport
        try:
            response = transport(self.endpoint, payload, headers, self.timeout_sec)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise SuggestionEngineError(f"LLM request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise SuggestionEngineError(f"LLM response decode failed: {exc}") from exc

        suggestions = _parse_llm_response(track_id=track_id, profile=profile, payload=response)
        if not suggestions:
            raise SuggestionEngineError("LLM response contains no valid candidates")
        return suggestions


def _default_http_transport(
    endpoint: str,
    payload: dict[str, object],
    headers: dict[str, str],
    timeout_sec: float,
) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = Request(endpoint, data=body, headers=headers, method="POST")
    with urlopen(req, timeout=timeout_sec) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise SuggestionEngineError("LLM response must be a JSON object")
    return decoded


def _parse_llm_response(track_id: str, profile: MixProfile, payload: dict[str, object]) -> list[Suggestion]:
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        return []

    suggestions: list[Suggestion] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        param_updates = _parse_param_updates(raw.get("param_updates"))
        if not param_updates:
            continue
        variant = str(raw.get("variant") or "llm")
        reason = str(raw.get("reason") or "llm-generated")
        try:
            score = float(raw.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0

        suggestions.append(
            Suggestion(
                suggestion_id=str(uuid4()),
                track_id=track_id,
                profile=profile,
                variant=variant,
                score=score,
                reason=reason,
                param_updates=param_updates,
            )
        )

    suggestions.sort(key=lambda item: item.score, reverse=True)
    return suggestions[:3]


def _parse_param_updates(raw: object) -> dict[BuiltinEffectType, dict[str, float]]:
    if not isinstance(raw, dict):
        return {}
    updates: dict[BuiltinEffectType, dict[str, float]] = {}
    for effect_name, params in raw.items():
        if not isinstance(effect_name, str):
            continue
        try:
            effect_type = BuiltinEffectType(effect_name.strip().lower())
        except ValueError:
            continue
        if not isinstance(params, dict):
            continue
        effect_params: dict[str, float] = {}
        for key, value in params.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, (int, float)):
                effect_params[key] = float(value)
        if effect_params:
            updates[effect_type] = effect_params
    return updates


def _feature_payload(features: TrackFeatures) -> dict[str, float]:
    return {
        "lufs": features.lufs,
        "peak_dbfs": features.peak_dbfs,
        "rms_dbfs": features.rms_dbfs,
        "crest_factor_db": features.crest_factor_db,
        "spectral_centroid_hz": features.spectral_centroid_hz,
        "band_energy_low": features.band_energy_low,
        "band_energy_mid": features.band_energy_mid,
        "band_energy_high": features.band_energy_high,
        "dynamic_range_db": features.dynamic_range_db,
        "loudness_range_db": features.loudness_range_db,
        "transient_density": features.transient_density,
        "zero_crossing_rate": features.zero_crossing_rate,
    }

