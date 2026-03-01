"""Contract-first API endpoints for mixing analysis and suggestions."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from music_create.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ComposeSuggestRequest,
    ComposeSuggestResponse,
    ComposeSuggestionCandidate,
    SuggestRequest,
    SuggestResponse,
    SuggestionCandidate,
)
from music_create.composition.models import ComposeRequest
from music_create.composition.service import CompositionService
from music_create.mixing.models import AnalysisMode, MixProfile
from music_create.mixing.service import MixingService
from music_create.ui.timeline import TimelineState


def create_app(
    mixing_service: MixingService | None = None,
    composition_service: CompositionService | None = None,
) -> FastAPI:
    app = FastAPI(title="music-create API", version="0.1.0")
    service = mixing_service or MixingService()
    compose_service = composition_service or CompositionService(TimelineState(bars=64))

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
            suggestions = service.suggest(
                track_id=payload.track_id,
                profile=profile,
                analysis_id=payload.analysis_id,
                mode=AnalysisMode(payload.mode),
                engine_mode=payload.suggestion_engine,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return SuggestResponse(
            candidates=[
                SuggestionCandidate(
                    suggestion_id=item.suggestion_id,
                    track_id=item.track_id,
                    profile=item.profile,
                    variant=item.variant,
                    score=item.score,
                    reason=item.reason,
                    param_updates={k.value: v for k, v in item.param_updates.items()},
                )
                for item in suggestions
            ]
        )

    @app.post("/v1/compose/suggest", response_model=ComposeSuggestResponse)
    def suggest_compose(payload: ComposeSuggestRequest) -> ComposeSuggestResponse:
        try:
            request = ComposeRequest(
                track_id=payload.track_id,
                part=payload.part,
                key=payload.key,
                scale=payload.scale,
                bars=payload.bars,
                style=payload.style,
                grid=payload.grid,
                program=payload.program,
            )
            suggestions = compose_service.suggest(request=request, engine_mode=payload.engine_mode)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return ComposeSuggestResponse(
            candidates=[
                ComposeSuggestionCandidate(
                    suggestion_id=item.suggestion_id,
                    track_id=item.request.track_id,
                    part=item.request.part,
                    key=item.request.key,
                    scale=item.request.scale,
                    bars=item.request.bars,
                    style=item.request.style,
                    grid=item.clips[0].grid,
                    source=item.source,
                    score=item.score,
                    reason=item.reason,
                    note_count=len(item.clips[0].notes),
                    clip_name=item.clips[0].name,
                )
                for item in suggestions
            ],
            source=compose_service.get_last_source(),
            fallback_reason=compose_service.get_last_fallback_reason(),
        )

    return app


app = create_app()
