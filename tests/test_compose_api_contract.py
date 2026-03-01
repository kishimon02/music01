from fastapi.testclient import TestClient

from music_create.api.server import create_app
from music_create.composition.service import CompositionService
from music_create.mixing.service import MixingService
from music_create.ui.timeline import TimelineState


def _signal_provider(_track_id: str) -> list[float]:
    return [0.1, -0.1, 0.05, -0.02] * 1000


def _base_payload() -> dict[str, object]:
    return {
        "track_id": "track-1",
        "part": "melody",
        "key": "C",
        "scale": "major",
        "bars": 4,
        "style": "pop",
        "program": 0,
    }


def test_compose_suggest_accepts_all_supported_grids() -> None:
    app = create_app(
        mixing_service=MixingService(track_signal_provider=_signal_provider),
        composition_service=CompositionService(timeline=TimelineState(bars=32)),
    )
    client = TestClient(app)
    allowed_grids = ["1", "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T", "1/16", "1/16T", "1/32", "1/32T", "1/64"]

    for grid in allowed_grids:
        payload = _base_payload()
        payload["grid"] = grid
        response = client.post("/v1/compose/suggest", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["candidates"]
        assert body["candidates"][0]["grid"] == grid


def test_compose_suggest_rejects_unsupported_grid() -> None:
    app = create_app(
        mixing_service=MixingService(track_signal_provider=_signal_provider),
        composition_service=CompositionService(timeline=TimelineState(bars=32)),
    )
    client = TestClient(app)

    payload = _base_payload()
    payload["grid"] = "1/128"
    response = client.post("/v1/compose/suggest", json=payload)
    assert response.status_code == 422

