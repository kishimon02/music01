from music_create.mixing.service import MixingService
from music_create.mixing.suggestion_engine import LLMSuggestionEngine


def _signal_provider(track_id: str) -> list[float]:
    if track_id == "kick":
        return [0.2, 0.4, -0.3, 0.1] * 1000
    return [0.05, -0.05, 0.03, -0.02] * 1000


def test_llm_mode_uses_llm_candidates_when_available() -> None:
    def _transport(_endpoint: str, _payload: dict[str, object], _headers: dict[str, str], _timeout: float) -> dict[str, object]:
        return {
            "candidates": [
                {
                    "variant": "llm-tight",
                    "score": 0.91,
                    "reason": "generated-by-llm",
                    "param_updates": {
                        "compressor": {"ratio": 5.1, "threshold_db": -24.0},
                        "saturator": {"mix": 0.44},
                    },
                }
            ]
        }

    llm = LLMSuggestionEngine(endpoint="https://llm.example.local/v1/mix/suggest", transport=_transport)
    service = MixingService(
        track_signal_provider=_signal_provider,
        suggestion_mode="llm-based",
        llm_suggestion_engine=llm,
    )

    suggestions = service.suggest(track_id="kick", profile="punch")
    assert suggestions
    assert suggestions[0].variant == "llm-tight"
    assert service.get_last_suggestion_source() == "llm-based"
    assert service.get_last_suggestion_fallback_reason() is None


def test_llm_mode_falls_back_to_rule_based_when_llm_fails() -> None:
    def _transport(_endpoint: str, _payload: dict[str, object], _headers: dict[str, str], _timeout: float) -> dict[str, object]:
        raise TimeoutError("llm timeout")

    llm = LLMSuggestionEngine(endpoint="https://llm.example.local/v1/mix/suggest", transport=_transport)
    service = MixingService(
        track_signal_provider=_signal_provider,
        suggestion_mode="llm-based",
        llm_suggestion_engine=llm,
        fallback_to_rule_on_llm_error=True,
    )

    suggestions = service.suggest(track_id="kick", profile="clean")
    assert len(suggestions) >= 3
    assert service.get_last_suggestion_source() == "rule-based-fallback"
    reason = service.get_last_suggestion_fallback_reason()
    assert reason is not None
    assert "timeout" in reason
    assert "fallback=" in suggestions[0].reason
