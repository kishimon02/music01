import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

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


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_integrated_window_builds_studio_workspace(monkeypatch, qapp) -> None:
    monkeypatch.setattr(app_module, "NativeAudioEngine", _DummyNativeAudioEngine)

    window = app_module.IntegratedWindow()
    try:
        assert window.transport_title_label.text() == "music-create"
        assert window.playhead_slider.minimum() == 100
        assert window.inspector_tabs.count() == 3
        assert [window.inspector_tabs.tabText(index) for index in range(window.inspector_tabs.count())] == [
            "トラック",
            "作曲",
            "ミックス",
        ]
        assert window.utility_tabs.count() == 5
        assert [window.utility_tabs.tabText(index) for index in range(window.utility_tabs.count())] == [
            "ミックス提案",
            "ミックス履歴",
            "作曲提案",
            "A/B比較",
            "作曲履歴",
        ]
    finally:
        window.close()
