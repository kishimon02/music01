from music_create.mixing.service import MixingService
from music_create.mixing.models import BuiltinEffectType


def _signal_provider(track_id: str) -> list[float]:
    if track_id == "kick":
        return [0.2, 0.4, -0.3, 0.1] * 1000
    return [0.05, -0.05, 0.03, -0.02] * 1000


def test_apply_and_revert_suggestion() -> None:
    service = MixingService(track_signal_provider=_signal_provider)

    suggestions = service.suggest(track_id="kick", profile="punch")
    suggestion = suggestions[0]
    assert len(suggestions) >= 3
    assert suggestions[0].score >= suggestions[1].score >= suggestions[2].score

    graph = service.get_mixer_graph()
    before_ratio = graph.tracks["kick"].fx_chain.effects[BuiltinEffectType.COMPRESSOR].parameters["ratio"]

    command_id = service.apply(track_id="kick", suggestion_id=suggestion.suggestion_id)
    after_ratio = graph.tracks["kick"].fx_chain.effects[BuiltinEffectType.COMPRESSOR].parameters["ratio"]

    assert after_ratio != before_ratio

    service.revert(command_id)
    reverted_ratio = graph.tracks["kick"].fx_chain.effects[BuiltinEffectType.COMPRESSOR].parameters["ratio"]
    assert reverted_ratio == before_ratio


def test_preview_is_nonpersistent_after_apply_revert_cycle() -> None:
    service = MixingService(track_signal_provider=_signal_provider)
    suggestion = service.suggest(track_id="snare", profile="clean")[0]

    graph = service.get_mixer_graph()
    original = graph.tracks["snare"].fx_chain.effects[BuiltinEffectType.SATURATOR].parameters["mix"]

    service.preview("snare", suggestion.suggestion_id, dry_wet=0.5)
    previewed = graph.tracks["snare"].fx_chain.effects[BuiltinEffectType.SATURATOR].parameters["mix"]
    assert previewed != original

    service.cancel_preview("snare")
    restored = graph.tracks["snare"].fx_chain.effects[BuiltinEffectType.SATURATOR].parameters["mix"]
    assert restored == original


def test_analyze_id_roundtrip() -> None:
    service = MixingService(track_signal_provider=_signal_provider)
    analysis_id = service.analyze(track_ids=["kick"], mode="quick")
    snapshot = service.get_snapshot(analysis_id)
    assert snapshot.analysis_id == analysis_id
    assert "kick" in snapshot.track_features


def test_full_analysis_exposes_extended_features() -> None:
    service = MixingService(track_signal_provider=_signal_provider)
    analysis_id = service.analyze(track_ids=["kick"], mode="full")
    snapshot = service.get_snapshot(analysis_id)
    features = snapshot.track_features["kick"]

    assert features.crest_factor_db >= 0.0
    assert features.loudness_range_db >= 0.0
    assert 0.0 <= features.transient_density <= 1.0
    assert 0.0 <= features.zero_crossing_rate <= 1.0


def test_suggest_can_reuse_existing_analysis_snapshot() -> None:
    service = MixingService(track_signal_provider=_signal_provider)
    analysis_id = service.analyze(track_ids=["kick"], mode="full")
    _ = service.get_snapshot(analysis_id)

    suggestions = service.suggest(track_id="kick", profile="clean", analysis_id=analysis_id, mode="full")
    assert len(suggestions) >= 3


def test_apply_uses_baseline_even_after_preview() -> None:
    service = MixingService(track_signal_provider=_signal_provider)
    suggestions = service.suggest(track_id="kick", profile="punch")
    suggestion = suggestions[0]
    graph = service.get_mixer_graph()

    service.preview("kick", suggestion.suggestion_id, dry_wet=0.5)
    service.apply("kick", suggestion.suggestion_id)
    ratio_after_preview_then_apply = graph.tracks["kick"].fx_chain.effects[BuiltinEffectType.COMPRESSOR].parameters[
        "ratio"
    ]

    fresh = MixingService(track_signal_provider=_signal_provider)
    fresh_suggestion = fresh.suggest(track_id="kick", profile="punch")[0]
    fresh.apply("kick", fresh_suggestion.suggestion_id)
    ratio_direct_apply = fresh.get_mixer_graph().tracks["kick"].fx_chain.effects[BuiltinEffectType.COMPRESSOR].parameters[
        "ratio"
    ]

    assert ratio_after_preview_then_apply == ratio_direct_apply


def test_command_history_tracks_apply_and_revert_state() -> None:
    service = MixingService(track_signal_provider=_signal_provider)
    suggestion = service.suggest(track_id="kick", profile="clean")[0]
    command_id = service.apply("kick", suggestion.suggestion_id)

    history = service.get_command_history(track_id="kick")
    assert history
    assert history[0].command_id == command_id
    assert history[0].applied is True

    service.revert(command_id)
    history_after_revert = service.get_command_history(track_id="kick")
    assert history_after_revert[0].applied is False


def test_get_track_state_returns_detached_copy() -> None:
    service = MixingService(track_signal_provider=_signal_provider)
    snapshot = service.get_track_state("kick")

    snapshot.fx_chain.effects[BuiltinEffectType.SATURATOR].parameters["mix"] = 0.8
    original = service.get_mixer_graph().tracks["kick"].fx_chain.effects[BuiltinEffectType.SATURATOR].parameters["mix"]
    assert original != 0.8


def test_suggestion_mode_can_be_updated() -> None:
    service = MixingService(track_signal_provider=_signal_provider)
    assert service.get_suggestion_mode() == "rule-based"
    service.set_suggestion_mode("llm-based")
    assert service.get_suggestion_mode() == "llm-based"
