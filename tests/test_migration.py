from music_create.project.migration import migrate_to_v2


def test_migrate_v1_to_v2_adds_mixing_extensions() -> None:
    legacy = {
        "format_version": 1,
        "meta": {"title": "demo"},
        "tracks": [{"id": "t1"}, {"id": "t2"}],
    }

    migrated = migrate_to_v2(legacy)
    dumped = migrated.model_dump()

    assert dumped["format_version"] == 2
    assert "mixer_graph" in dumped
    assert "builtin_fx_states" in dumped
    assert "analysis_snapshots" in dumped
    assert "suggestion_history" in dumped

    track_t1 = dumped["mixer_graph"]["tracks"]["t1"]
    assert track_t1["fx_chain"]["eq"]["high_gain_db"] == 0.0


def test_v2_validation_passthrough() -> None:
    current = {
        "format_version": 2,
        "tracks": [{"id": "t1"}],
        "mixer_graph": {"tracks": {"t1": {"track_id": "t1"}}},
    }
    migrated = migrate_to_v2(current)
    assert migrated.format_version == 2
