from fastapi.testclient import TestClient

from music_create.api.server import create_app
from music_create.mixing.service import MixingService


def _signal_provider(track_id: str) -> list[float]:
    return [0.1, -0.1, 0.07, -0.02] * 1500


def test_mix_analyze_endpoint_returns_analysis_id() -> None:
    app = create_app(MixingService(track_signal_provider=_signal_provider))
    client = TestClient(app)

    response = client.post("/v1/mix/analyze", json={"track_ids": ["t1"], "mode": "quick"})
    body = response.json()

    assert response.status_code == 200
    assert "analysis_id" in body
    assert isinstance(body["analysis_id"], str)


def test_root_and_favicon_endpoints() -> None:
    app = create_app(MixingService(track_signal_provider=_signal_provider))
    client = TestClient(app)

    root_response = client.get("/")
    assert root_response.status_code == 200
    assert root_response.json()["status"] == "ok"
    assert root_response.json()["docs"] == "/docs"

    favicon_response = client.get("/favicon.ico")
    assert favicon_response.status_code == 204


def test_mix_suggest_endpoint_returns_candidates() -> None:
    app = create_app(MixingService(track_signal_provider=_signal_provider))
    client = TestClient(app)

    response = client.post(
        "/v1/mix/suggest",
        json={"track_id": "t1", "profile": "clean", "suggestion_engine": "rule-based"},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["candidates"]
    candidate = body["candidates"][0]
    assert "suggestion_id" in candidate
    assert "param_updates" in candidate
    assert "variant" in candidate
    assert "score" in candidate


def test_mix_suggest_accepts_llm_engine_field_with_fallback() -> None:
    app = create_app(MixingService(track_signal_provider=_signal_provider, suggestion_mode="llm-based"))
    client = TestClient(app)

    response = client.post("/v1/mix/suggest", json={"track_id": "t1", "profile": "clean", "suggestion_engine": "llm-based"})
    assert response.status_code == 200
    assert response.json()["candidates"]


def test_mix_suggest_can_use_existing_analysis_id() -> None:
    app = create_app(MixingService(track_signal_provider=_signal_provider))
    client = TestClient(app)

    analysis_res = client.post("/v1/mix/analyze", json={"track_ids": ["t1"], "mode": "full"})
    analysis_id = analysis_res.json()["analysis_id"]

    suggest_res = client.post(
        "/v1/mix/suggest",
        json={"track_id": "t1", "profile": "warm", "analysis_id": analysis_id, "mode": "full"},
    )
    assert suggest_res.status_code == 200
    assert len(suggest_res.json()["candidates"]) >= 3


def test_mix_suggest_rejects_invalid_profile() -> None:
    app = create_app(MixingService(track_signal_provider=_signal_provider))
    client = TestClient(app)

    response = client.post("/v1/mix/suggest", json={"track_id": "t1", "profile": "invalid"})
    assert response.status_code == 422


def test_mix_suggest_rejects_invalid_suggestion_engine() -> None:
    app = create_app(MixingService(track_signal_provider=_signal_provider))
    client = TestClient(app)

    response = client.post("/v1/mix/suggest", json={"track_id": "t1", "profile": "clean", "suggestion_engine": "x"})
    assert response.status_code == 422
