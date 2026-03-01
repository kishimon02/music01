from music_create.composition.llm import CompositionLLMEngine
from music_create.composition.models import ComposeRequest, SUPPORTED_GRIDS
from music_create.composition.quantize import grid_to_step_ticks
from music_create.composition.service import CompositionService
from music_create.ui.timeline import TimelineState


def test_rule_based_suggest_supports_all_grids() -> None:
    timeline = TimelineState(bars=32)
    service = CompositionService(timeline=timeline, engine_mode="rule-based")

    for grid in SUPPORTED_GRIDS:
        request = ComposeRequest(
            track_id="track-compose",
            part="melody",
            key="C",
            scale="major",
            bars=4,
            style="pop",
            grid=grid,
            program=0,
        )
        suggestions = service.suggest(request=request, engine_mode="rule-based")
        assert suggestions
        step = grid_to_step_ticks(grid)
        for note in suggestions[0].clips[0].notes:
            assert note.start_tick % step == 0
            assert note.length_tick % step == 0


def test_llm_invalid_grid_falls_back_to_rule_based() -> None:
    def _transport(_endpoint: str, _payload: dict[str, object], _headers: dict[str, str], _timeout: float) -> dict[str, object]:
        return {
            "candidates": [
                {
                    "name": "invalid-grid-candidate",
                    "grid": "1/128",
                    "score": 0.9,
                    "notes": [
                        {"start_tick": 0, "length_tick": 240, "pitch": 60, "velocity": 90, "channel": 0},
                    ],
                }
            ]
        }

    llm = CompositionLLMEngine(endpoint="https://llm.example.local/v1/compose/suggest", transport=_transport)
    timeline = TimelineState(bars=32)
    service = CompositionService(
        timeline=timeline,
        engine_mode="llm-based",
        llm_engine=llm,
        fallback_to_rule_on_llm_error=True,
    )

    suggestions = service.suggest(
        request=ComposeRequest(
            track_id="track-compose",
            part="chord",
            key="C",
            scale="major",
            bars=4,
            style="pop",
            grid="1/16",
            program=0,
        ),
        engine_mode="llm-based",
    )

    assert suggestions
    assert service.get_last_source() == "rule-based-fallback"
    reason = service.get_last_fallback_reason()
    assert reason is not None
    assert "invalid grid" in reason
    assert suggestions[0].source == "rule-based-fallback"


def test_preview_apply_and_revert_with_triplet_grid() -> None:
    timeline = TimelineState(bars=32)
    service = CompositionService(timeline=timeline, engine_mode="rule-based")

    request = ComposeRequest(
        track_id="track-compose",
        part="drum",
        key="C",
        scale="major",
        bars=2,
        style="hiphop",
        grid="1/8T",
        program=None,
    )
    suggestions = service.suggest(request=request, engine_mode="rule-based")
    suggestion = suggestions[0]

    preview_path = service.preview(suggestion.suggestion_id)
    assert preview_path.exists()
    assert preview_path.suffix == ".wav"

    command_id, clip_ids = service.apply_to_timeline(suggestion.suggestion_id)
    assert command_id
    assert clip_ids
    for clip_id in clip_ids:
        assert clip_id in timeline.clips
        assert timeline.midi_clip_data[clip_id]["grid"] == "1/8T"

    service.revert(command_id)
    for clip_id in clip_ids:
        assert clip_id not in timeline.clips


def test_apply_to_timeline_appends_after_existing_clip() -> None:
    timeline = TimelineState(bars=16)
    track = timeline.add_track("Compose Track")
    timeline.add_clip(track.track_id, "midi", start_bar=1, length_bars=4, name="Existing MIDI")
    service = CompositionService(timeline=timeline, engine_mode="rule-based")

    suggestions = service.suggest(
        request=ComposeRequest(
            track_id=track.track_id,
            part="chord",
            key="C",
            scale="major",
            bars=4,
            style="pop",
            grid="1/16",
            program=0,
        )
    )
    _, clip_ids = service.apply_to_timeline(suggestions[0].suggestion_id)

    inserted_clip = timeline.clips[clip_ids[0]]
    assert inserted_clip.start_bar == 5
    assert inserted_clip.length_bars == 4
