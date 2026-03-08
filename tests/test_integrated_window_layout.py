import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from music_create.ui import app as app_module


class _DummyNativeAudioEngine:
    def __init__(self, *args, **kwargs) -> None:
        self._available = False

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def stop_playback(self) -> None:
        return None

    def is_available(self) -> bool:
        return self._available


class _DummySettings:
    _store: dict[str, object] = {}

    def __init__(self, *args, **kwargs) -> None:
        return None

    def value(self, key: str, default: object = None) -> object:
        return self._store.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        self._store[key] = value


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def window(monkeypatch, qapp):
    monkeypatch.setattr(app_module, "NativeAudioEngine", _DummyNativeAudioEngine)
    monkeypatch.setattr(app_module, "QSettings", _DummySettings)
    _DummySettings._store = {}

    created = app_module.IntegratedWindow()
    created.show()
    qapp.processEvents()
    try:
        yield created
    finally:
        created.close()


def test_integrated_window_builds_studio_workspace(window) -> None:
    assert window.transport_title_label.text() == "music-create"
    assert window._timeline.bars == 64
    assert window._timeline.max_bars == 1000
    assert window.display_mode_combo.count() == 2
    assert window.inspector_tabs.count() == 3
    assert [window.inspector_tabs.tabText(index) for index in range(window.inspector_tabs.count())] == [
        "トラック",
        "作曲",
        "ミックス",
    ]
    assert window.utility_tabs.count() == 6
    assert [window.utility_tabs.tabText(index) for index in range(window.utility_tabs.count())] == [
        "エディタ",
        "ミックス提案",
        "ミックス履歴",
        "作曲提案",
        "A/B比較",
        "作曲履歴",
    ]
    assert window.arranger_view.objectName() == "arrangerQuick"
    assert window.transport_view.objectName() == "transportQuick"
    assert window.editor_scroll_area.objectName() == "editorScrollArea"


def test_integrated_window_toggles_workspace_panels(window, qapp) -> None:
    assert window.inspector_panel.isVisible() is True
    assert window.utility_rack.isVisible() is True

    window._toggle_inspector_panel()
    window._toggle_rack_panel()
    qapp.processEvents()

    assert window.inspector_panel.isVisible() is False
    assert window.utility_rack.isVisible() is False
    assert window.toggle_inspector_button.text() == "インスペクタを表示"
    assert window.toggle_rack_button.text() == "下部ラックを表示"


def test_editor_tab_uses_internal_scroll_and_keeps_piano_roll_reachable(window, qapp) -> None:
    window.resize(1500, 940)
    window.utility_tabs.setCurrentWidget(window.editor_tab)
    qapp.processEvents()

    scrollbar = window.editor_scroll_area.verticalScrollBar()
    assert scrollbar.maximum() > 0

    window.editor_scroll_area.ensureWidgetVisible(window.piano_roll_view)
    qapp.processEvents()

    top_left = window.piano_roll_view.mapTo(window.editor_scroll_area.viewport(), QPoint(0, 0))
    bottom_left = window.piano_roll_view.mapTo(window.editor_scroll_area.viewport(), QPoint(0, window.piano_roll_view.height()))
    assert top_left.y() < window.editor_scroll_area.viewport().height()
    assert bottom_left.y() > 0


def test_arranger_selection_opens_editor_and_syncs_midi_clip(window, qapp) -> None:
    clip = window._timeline.clips_for_track("track-1")[0]
    window._apply_rack_collapsed_state(True)
    qapp.processEvents()

    window._on_arranger_selection_requested(clip.track_id, clip.start_bar, clip.clip_id)
    qapp.processEvents()

    assert window.utility_rack.isVisible() is True
    assert window.utility_tabs.currentWidget() is window.editor_tab
    assert window.selected_clip_id == clip.clip_id
    assert window._selected_midi_clip_id == clip.clip_id
    assert window.piano_roll_view.has_notes() is True


def test_compose_apply_syncs_arranger_and_editor(window, qapp) -> None:
    window.compose_track_input.setText("track-1")
    window.compose_bars_spin.setValue(2)
    window._on_compose_suggest()
    qapp.processEvents()
    assert window.compose_suggestion_list.count() > 0

    before_ids = set(window._timeline.clips)
    window._on_compose_apply()
    qapp.processEvents()

    after_ids = set(window._timeline.clips)
    created_ids = after_ids - before_ids
    assert created_ids
    assert window.utility_tabs.currentWidget() is window.editor_tab
    assert window.selected_clip_id in created_ids
    assert window._selected_timeline_bar == window._timeline.clips[window.selected_clip_id].start_bar

    scene_clip_ids = {
        clip_data["clipId"]
        for track_data in window._timeline_scene_model.get_tracks()
        for clip_data in track_data["clips"]
    }
    assert window.selected_clip_id in scene_clip_ids


def test_pencil_creation_adds_clip_to_existing_track(window, qapp) -> None:
    before_count = len(window._timeline.clips)
    clip = window.create_clip_from_arranger_drag("track-1", 9, 12, 0)
    qapp.processEvents()

    assert clip is not None
    assert len(window._timeline.clips) == before_count + 1
    assert clip.track_id == "track-1"
    assert clip.length_bars == 4
    assert window.selected_clip_id == clip.clip_id
    assert window.utility_tabs.currentWidget() is window.editor_tab


def test_pencil_creation_can_create_new_instrument_track(window, monkeypatch, qapp) -> None:
    before_track_count = len(window._timeline.tracks)
    monkeypatch.setattr(
        window,
        "_prompt_arranger_instrument_choice",
        lambda: ("ベル", 10, False, "#123456"),
    )

    clip = window.create_clip_from_arranger_drag(None, 17, 20, before_track_count)
    qapp.processEvents()

    assert clip is not None
    assert len(window._timeline.tracks) == before_track_count + 1
    new_track = window._timeline.tracks[clip.track_id]
    assert new_track.instrument_name == "ベル"
    assert new_track.program == 10
    assert new_track.color == "#123456"


def test_arranger_zoom_buttons_share_combo_state(window, qapp) -> None:
    assert window.arranger_zoom_combo.currentData() == 16

    window._on_arranger_zoom_in()
    qapp.processEvents()
    assert window.arranger_zoom_combo.currentData() == 32
    assert window._timeline_scene_model.get_zoom_level() == 32

    window._on_arranger_zoom_out()
    qapp.processEvents()
    assert window.arranger_zoom_combo.currentData() == 16
    assert window._timeline_scene_model.get_zoom_level() == 16
