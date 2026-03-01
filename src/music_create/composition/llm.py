"""LLM-based composition suggestion integration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from music_create.composition.models import ComposeRequest, ComposeSuggestion, MidiClipDraft, MidiNoteEvent, is_valid_grid
from music_create.composition.quantize import quantize_note

_HTTPTransport = Callable[[str, dict[str, object], dict[str, str], float], dict[str, object]]


class CompositionLLMError(RuntimeError):
    """Raised when LLM generation fails."""


@dataclass(slots=True)
class CompositionLLMEngine:
    endpoint: str = ""
    api_key: str = ""
    timeout_sec: float = 6.0
    model: str = ""
    transport: _HTTPTransport | None = None

    @staticmethod
    def from_env() -> CompositionLLMEngine:
        endpoint = os.getenv("MUSIC_CREATE_LLM_ENDPOINT", "").strip()
        api_key = os.getenv("MUSIC_CREATE_LLM_API_KEY", "").strip()
        model = os.getenv("MUSIC_CREATE_LLM_MODEL", "").strip()
        timeout_raw = os.getenv("MUSIC_CREATE_LLM_TIMEOUT_SEC", "6.0").strip()
        try:
            timeout = float(timeout_raw)
        except ValueError:
            timeout = 6.0
        return CompositionLLMEngine(
            endpoint=endpoint,
            api_key=api_key,
            timeout_sec=max(timeout, 0.1),
            model=model,
        )

    def suggest(self, request: ComposeRequest) -> list[ComposeSuggestion]:
        request.validate()
        if not self.endpoint:
            raise CompositionLLMError("MUSIC_CREATE_LLM_ENDPOINT is not configured")

        payload = {
            "task": "compose_suggest",
            "track_id": request.track_id,
            "part": request.part,
            "key": request.key,
            "scale": request.scale,
            "bars": request.bars,
            "style": request.style,
            "grid": request.grid,
            "program": request.program,
            "model": self.model or None,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        transport = self.transport or _default_http_transport
        try:
            response = transport(self.endpoint, payload, headers, self.timeout_sec)
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            raise CompositionLLMError(f"LLM request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise CompositionLLMError(f"LLM response decode failed: {exc}") from exc

        suggestions = _parse_candidates(request, response)
        if not suggestions:
            raise CompositionLLMError("LLM response has no valid candidates")
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
        raise CompositionLLMError("LLM response must be a JSON object")
    return decoded


def _parse_candidates(request: ComposeRequest, payload: dict[str, object]) -> list[ComposeSuggestion]:
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        return []
    output: list[ComposeSuggestion] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        raw_grid = str(raw.get("grid", request.grid))
        if not is_valid_grid(raw_grid):
            raise CompositionLLMError(f"invalid grid from llm: {raw_grid}")

        notes_raw = raw.get("notes")
        if not isinstance(notes_raw, list):
            continue
        notes: list[MidiNoteEvent] = []
        for item in notes_raw:
            if not isinstance(item, dict):
                continue
            try:
                start_tick = int(item.get("start_tick", 0))
                length_tick = int(item.get("length_tick", 0))
                pitch = int(item.get("pitch", 60))
                velocity = int(item.get("velocity", 90))
                channel = int(item.get("channel", 9 if request.part == "drum" else 0))
                q_start, q_len = quantize_note(start_tick, length_tick, raw_grid)  # type: ignore[arg-type]
                event = MidiNoteEvent(
                    start_tick=q_start,
                    length_tick=q_len,
                    pitch=min(max(pitch, 0), 127),
                    velocity=min(max(velocity, 1), 127),
                    channel=min(max(channel, 0), 15),
                )
                event.validate()
            except (TypeError, ValueError):
                continue
            notes.append(event)
        if not notes:
            continue

        clip = MidiClipDraft(
            name=str(raw.get("name", f"{request.part.title()} LLM")),
            bars=request.bars,
            grid=raw_grid,  # type: ignore[arg-type]
            notes=notes,
            program=request.program if request.part != "drum" else None,
            is_drum=request.part == "drum",
        )
        clip.validate()
        try:
            score = float(raw.get("score", 0.75))
        except (TypeError, ValueError):
            score = 0.75
        reason = str(raw.get("reason", "llm-generated"))
        output.append(
            ComposeSuggestion.new(
                request=request,
                score=score,
                source="llm-based",
                reason=reason,
                clips=[clip],
            )
        )

    output.sort(key=lambda item: item.score, reverse=True)
    return output[:3]

