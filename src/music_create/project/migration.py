"""Project migration helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from music_create.mixing.fx import default_fx_chain
from music_create.project.schema import MCPJProjectV2


def migrate_to_v2(project_data: dict[str, Any]) -> MCPJProjectV2:
    original = deepcopy(project_data)
    format_version = int(original.get("format_version", 1))

    if format_version == 2:
        return MCPJProjectV2.model_validate(original)
    if format_version != 1:
        raise ValueError(f"Unsupported format_version={format_version}")

    tracks = original.get("tracks", [])
    mixer_graph_tracks: dict[str, Any] = {}
    builtin_fx_states: dict[str, Any] = {}

    for idx, track in enumerate(tracks):
        if not isinstance(track, dict):
            continue
        track_id = str(track.get("id", f"track-{idx + 1}"))
        chain = default_fx_chain()
        effect_states = {
            effect_type.value: dict(fx_state.parameters)
            for effect_type, fx_state in chain.effects.items()
        }
        mixer_graph_tracks[track_id] = {
            "track_id": track_id,
            "input_gain_db": 0.0,
            "fx_chain": effect_states,
            "fader_db": 0.0,
            "pan": 0.0,
            "sends": [],
        }
        builtin_fx_states[track_id] = effect_states

    original["format_version"] = 2
    original["mixer_graph"] = {"tracks": mixer_graph_tracks}
    original["builtin_fx_states"] = builtin_fx_states
    original.setdefault("analysis_snapshots", [])
    original.setdefault("suggestion_history", [])

    return MCPJProjectV2.model_validate(original)
