"""Contract-first API endpoints for mixing analysis and suggestions."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from music_create.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    SuggestRequest,
    SuggestResponse,
    SuggestionCandidate,
)
from music_create.mixing.models import AnalysisMode, MixProfile
from music_create.mixing.service import MixingService


def create_app(mixing_service: MixingService | None = None) -> FastAPI:
    app = FastAPI(title="music-create API", version="0.1.0")
    service = mixing_service or MixingService()

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "service": "music-create API",
            "status": "ok",
            "docs": "/docs",
        }

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.post("/v1/mix/analyze", response_model=AnalyzeResponse)
    def analyze_mix(payload: AnalyzeRequest) -> AnalyzeResponse:
        try:
            mode = AnalysisMode(payload.mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        analysis_id = service.analyze(track_ids=payload.track_ids, mode=mode)
        return AnalyzeResponse(analysis_id=analysis_id)

    @app.post("/v1/mix/suggest", response_model=SuggestResponse)
    def suggest_mix(payload: SuggestRequest) -> SuggestResponse:
        try:
            profile: MixProfile = payload.profile
            suggestions = service.suggest(track_id=payload.track_id, profile=profile)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return SuggestResponse(
            candidates=[
                SuggestionCandidate(
                    suggestion_id=item.suggestion_id,
                    track_id=item.track_id,
                    profile=item.profile,
                    reason=item.reason,
                    param_updates={k.value: v for k, v in item.param_updates.items()},
                )
                for item in suggestions
            ]
        )

    return app


app = create_app()
