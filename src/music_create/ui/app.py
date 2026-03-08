"""Integrated desktop UI: timeline, waveform analysis, and native playback."""

from __future__ import annotations

import math
import sys
import tempfile
import time
import wave
from datetime import datetime
from pathlib import Path

from music_create.audio.mix_render import is_track_processing_active, render_track_preview_wav
from music_create.audio.native_engine import NativeAudioEngine
from music_create.audio.repository import WaveformRepository
from music_create.composition import Composition, CompositionService
from music_create.composition.models import (
    ComposeCommand,
    ComposeRequest,
    ComposeSuggestion,
    MidiClipDraft,
    MidiNoteEvent,
    SUPPORTED_GRIDS,
)
from music_create.composition.synth import render_clip_to_wav
from music_create.mixing import Mixing
from music_create.mixing.models import Suggestion, SuggestionCommand
from music_create.mixing.service import MixingService
from music_create.ui.piano_roll import PianoRollNote, SimplePianoRollView
from music_create.ui.quick_bridge import TimelineSceneModel, TransportState, WorkspaceLayoutState
from music_create.ui.timeline import TimelineClip, TimelineState, TimelineTrack
from music_create.ui.transport_display import (
    DISPLAY_MODE_BARS,
    DISPLAY_MODE_TIME,
    bar_to_seconds,
    format_clip_range,
    format_clock_time,
    format_transport_position,
    seconds_per_bar,
    seconds_to_bar,
)
from music_create.ui.waveform import WaveformView

try:
    from PySide6.QtCore import QSettings, QTimer, Qt, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQuickWidgets import QQuickWidget
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFrame,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSlider,
        QSpinBox,
        QSplitter,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover - runtime-only path
    QTimer = object  # type: ignore[assignment]
    QApplication = None  # type: ignore[assignment]
    QFileDialog = object  # type: ignore[assignment]
    QComboBox = object  # type: ignore[assignment]
    QFrame = object  # type: ignore[assignment]
    QFormLayout = object  # type: ignore[assignment]
    QGroupBox = object  # type: ignore[assignment]
    QHBoxLayout = object  # type: ignore[assignment]
    QInputDialog = object  # type: ignore[assignment]
    QLabel = object  # type: ignore[assignment]
    QLineEdit = object  # type: ignore[assignment]
    QListWidget = object  # type: ignore[assignment]
    QListWidgetItem = object  # type: ignore[assignment]
    QMainWindow = object  # type: ignore[assignment]
    QMessageBox = object  # type: ignore[assignment]
    QPushButton = object  # type: ignore[assignment]
    QScrollArea = object  # type: ignore[assignment]
    QSlider = object  # type: ignore[assignment]
    QSpinBox = object  # type: ignore[assignment]
    QSettings = object  # type: ignore[assignment]
    QSplitter = object  # type: ignore[assignment]
    QTabWidget = object  # type: ignore[assignment]
    QTextEdit = object  # type: ignore[assignment]
    QVBoxLayout = object  # type: ignore[assignment]
    QQuickWidget = object  # type: ignore[assignment]
    QWidget = object  # type: ignore[assignment]
    QColor = object  # type: ignore[assignment]
    QUrl = object  # type: ignore[assignment]
    Qt = object  # type: ignore[assignment]


def _demo_signal_provider(track_id: str) -> list[float]:
    seed = max(sum(ord(ch) for ch in track_id), 1)
    base_freq = 50 + (seed % 180)
    upper_freq = base_freq * (1.7 + (seed % 5) * 0.1)
    transient_interval = 240 + (seed % 120)

    samples: list[float] = []
    for idx in range(9600):
        t = idx / 48_000.0
        tone = 0.45 * math.sin(2 * math.pi * base_freq * t)
        overtone = 0.18 * math.sin(2 * math.pi * upper_freq * t)
        transient = 0.0
        if idx % transient_interval == 0:
            transient = 0.30 if (idx // transient_interval) % 2 == 0 else -0.28
        samples.append(max(min(tone + overtone + transient, 1.0), -1.0))
    return samples


def composition_grid_options() -> tuple[str, ...]:
    return SUPPORTED_GRIDS


def composition_instrument_options() -> tuple[tuple[str, int], ...]:
    return (
        ("ピアノ", 0),
        ("エレピ", 4),
        ("オルガン", 16),
        ("アコースティックギター", 24),
        ("エレキギター", 29),
        ("ベース", 33),
        ("ストリングス", 48),
        ("アンサンブル", 50),
        ("ブラス", 61),
        ("サックス", 65),
        ("フルート", 73),
        ("シンセリード", 80),
        ("シンセパッド", 88),
        ("ベル", 10),
        ("マリンバ", 12),
        ("プラック", 104),
    )


def arranger_instrument_options() -> tuple[tuple[str, int | None, bool], ...]:
    return tuple((label, program, False) for label, program in composition_instrument_options()) + (("ドラム", None, True),)


def instrument_name_from_program(program: int | None, *, is_drum: bool = False) -> str:
    if is_drum:
        return "ドラム"
    for label, value in composition_instrument_options():
        if value == program:
            return label
    return f"Program {program if program is not None else 0}"


def track_color_for_program(program: int | None, *, is_drum: bool = False) -> str:
    if is_drum:
        return "#FF8A4C"
    palette = ("#4D8FF4", "#66B7FF", "#74D39E", "#E4B84D", "#C28EFF", "#5CC7C8")
    return palette[(program or 0) % len(palette)]


def midi_note_name(pitch: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    normalized = min(max(int(pitch), 0), 127)
    octave = (normalized // 12) - 1
    return f"{names[normalized % 12]}{octave}"


def _studio_one_stylesheet() -> str:
    return """
    QWidget#appShell {
        background: #16181D;
        color: #E7ECF4;
    }
    QFrame#transportBar,
    QGroupBox {
        background: #1E232B;
        border: 1px solid #2D3641;
        border-radius: 12px;
    }
    QFrame#transportBar {
        border: 1px solid #303945;
    }
    QGroupBox {
        margin-top: 12px;
        padding-top: 10px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 6px;
        color: #9AA6B5;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
    }
    QLabel#shellTitle {
        color: #F2F6FB;
        font-size: 24px;
        font-weight: 700;
        letter-spacing: 1px;
    }
    QLabel#shellSubtitle {
        color: #8C98A7;
        font-size: 11px;
        letter-spacing: 2px;
        text-transform: uppercase;
    }
    QLabel[shellBadge="true"] {
        background: #262D36;
        border: 1px solid #384352;
        border-radius: 999px;
        color: #D7E0EC;
        font-size: 11px;
        font-weight: 600;
        padding: 7px 12px;
        min-width: 120px;
    }
    QLabel#transportMetric {
        color: #C3CEDB;
        font-size: 12px;
        font-weight: 600;
    }
    QLabel#statusStrip {
        background: #181C22;
        border: 1px solid #2B3440;
        border-radius: 8px;
        color: #E7ECF4;
        padding: 8px 12px;
    }
    QLabel#panelCaption,
    QLabel#sectionLabel {
        color: #9AA6B5;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
        text-transform: uppercase;
    }
    QLabel#panelHeadline {
        color: #F0F4FA;
        font-size: 14px;
        font-weight: 700;
    }
    QTabWidget::pane {
        border: 1px solid #2D3641;
        background: #1B2027;
        border-radius: 10px;
        top: -1px;
    }
    QTabBar::tab {
        background: #20262F;
        border: 1px solid #2D3641;
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        color: #8F9BAA;
        padding: 8px 14px;
        margin-right: 4px;
        min-width: 86px;
    }
    QTabBar::tab:selected {
        background: #262D36;
        color: #E7ECF4;
    }
    QTabBar::tab:hover {
        color: #F5F8FC;
    }
    QLineEdit,
    QComboBox,
    QSpinBox,
    QTextEdit,
    QListWidget,
    QTableWidget,
    QScrollArea {
        background: #161B21;
        border: 1px solid #2E3743;
        border-radius: 8px;
        color: #E7ECF4;
        selection-background-color: #355C90;
        selection-color: #F7FAFD;
    }
    QScrollArea {
        background: transparent;
    }
    QLineEdit,
    QComboBox,
    QSpinBox {
        min-height: 32px;
        padding: 4px 10px;
    }
    QTextEdit,
    QListWidget,
    QTableWidget {
        padding: 6px;
    }
    QListWidget::item {
        border-radius: 6px;
        padding: 6px 8px;
    }
    QListWidget::item:selected {
        background: #314B72;
    }
    QPushButton {
        background: #252C35;
        border: 1px solid #384454;
        border-radius: 8px;
        color: #E7ECF4;
        font-weight: 600;
        min-height: 32px;
        padding: 5px 12px;
    }
    QPushButton:hover {
        background: #2B3540;
    }
    QPushButton:pressed {
        background: #1F252D;
    }
    QPushButton:checked {
        background: #314B72;
        border: 1px solid #67A3FF;
        color: #F7FAFD;
    }
    QPushButton[accent="true"] {
        background: #4D8FF4;
        border: 1px solid #67A3FF;
        color: #0D1117;
    }
    QPushButton[accent="true"]:hover {
        background: #62A0FF;
    }
    QPushButton[danger="true"] {
        background: #332721;
        border: 1px solid #A95B35;
        color: #FFB892;
    }
    QPushButton[danger="true"]:hover {
        background: #443128;
    }
    QSlider::groove:horizontal {
        background: #222932;
        border: 1px solid #2F3946;
        border-radius: 4px;
        height: 8px;
    }
    QSlider::sub-page:horizontal {
        background: #4D8FF4;
        border-radius: 4px;
    }
    QSlider::handle:horizontal {
        background: #F4F7FB;
        border: 1px solid #607286;
        width: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }
    QHeaderView::section {
        background: #20262F;
        border: 0;
        border-right: 1px solid #2F3946;
        border-bottom: 1px solid #2F3946;
        color: #9FAABA;
        font-weight: 600;
        padding: 6px 8px;
    }
    QTableWidget {
        gridline-color: #2B3440;
    }
    QSplitter::handle {
        background: #14181D;
    }
    QSplitter::handle:horizontal {
        width: 5px;
    }
    QSplitter::handle:vertical {
        height: 5px;
    }
    """


class IntegratedWindow(QMainWindow):
    def __init__(self, mixing: Mixing | None = None) -> None:
        super().__init__()
        self.setWindowTitle("music-create 統合UI")
        self.resize(1500, 940)
        self.setMinimumSize(1360, 900)

        self._waveforms = WaveformRepository()
        self._native_engine: NativeAudioEngine | None = None
        try:
            self._native_engine = NativeAudioEngine(auto_build=True)
            self._native_engine.start()
        except Exception:
            self._native_engine = None

        if mixing is None:
            service = MixingService(track_signal_provider=self._track_signal_provider)
            self._mixing = Mixing(service=service)
        else:
            self._mixing = mixing

        self._latest_analysis_id: str | None = None
        self._suggestions: dict[str, Suggestion] = {}
        self._compose_suggestions: dict[str, ComposeSuggestion] = {}
        self._compose_ab_slots: dict[str, str | None] = {"A": None, "B": None}
        self.selected_clip_id: str | None = None
        self._selected_midi_clip_id: str | None = None
        self._selected_timeline_bar = 1
        self._updating_roll_from_model = False
        self._settings = QSettings("music-create", "music-create") if QSettings is not object else None
        self._arranger_zoom_levels = (4, 8, 16, 32, 64)
        self.tool_mode = self._setting_str("workspace/tool_mode", "select")
        if self.tool_mode not in {"select", "pencil"}:
            self.tool_mode = "select"
        self.pending_track_creation_from_pencil: tuple[int, int, int] | None = None
        self._timeline = TimelineState(bars=64, max_bars=1000, expansion_chunk=64, expand_threshold_bars=8)
        self._composition = Composition(service=CompositionService(self._timeline))
        self._init_default_timeline()
        self._preview_render_dir = Path(tempfile.gettempdir()) / "music_create" / "preview_wav"
        self._preview_render_dir.mkdir(parents=True, exist_ok=True)
        self._tempo_bpm = 120.0
        self._beats_per_bar = 4.0
        zoom_level = self._setting_int("workspace/zoom_level", 16)
        if zoom_level not in self._arranger_zoom_levels:
            zoom_level = 16
        self._workspace_layout = WorkspaceLayoutState(
            inspector_collapsed=self._setting_bool("workspace/inspector_collapsed", False),
            rack_collapsed=self._setting_bool("workspace/rack_collapsed", False),
            display_mode=self._setting_str("workspace/display_mode", DISPLAY_MODE_BARS),
            zoom_level=zoom_level,
        )
        self._transport_state = TransportState()
        self._timeline_scene_model = TimelineSceneModel()
        self._inspector_last_width = self._setting_int("workspace/inspector_width", 360)
        self._rack_last_height = self._setting_int("workspace/rack_height", 360)
        self._playback_track_id: str | None = None
        self._playback_started_at: float | None = None
        self._playback_duration_sec = 0.0
        self._playback_elapsed_sec = 0.0
        self._playback_timer: QTimer | None = None
        if QTimer is not object:
            self._playback_timer = QTimer(self)
            self._playback_timer.setInterval(33)
            self._playback_timer.timeout.connect(self._on_playback_tick)
        self._transport_state.playheadRequested.connect(self._on_transport_playhead_requested)
        self._timeline_scene_model.selectionRequested.connect(self._on_arranger_selection_requested)
        self._timeline_scene_model.clipCreationRequested.connect(self._on_arranger_clip_creation_requested)
        self._timeline_scene_model.zoomInRequested.connect(self._on_arranger_zoom_in)
        self._timeline_scene_model.zoomOutRequested.connect(self._on_arranger_zoom_out)
        self._timeline_scene_model.set_tool_mode(self.tool_mode)

        self._build_ui()
        self._sync_track_controls_from_timeline()
        self._refresh_timeline_view()
        self._refresh_wav_info()

    def _init_default_timeline(self) -> None:
        track1 = self._timeline.add_track(
            "Keys 1",
            instrument_name="ピアノ",
            program=0,
            color=track_color_for_program(0),
        )
        track2 = self._timeline.add_track(
            "Drums 1",
            instrument_name="ドラム",
            program=None,
            is_drum=True,
            color=track_color_for_program(None, is_drum=True),
        )
        self._timeline.add_clip(
            track1.track_id,
            "midi",
            start_bar=1,
            length_bars=4,
            name="Intro Chords",
            midi_data={
                "name": "Intro Chords",
                "bars": 4,
                "grid": "1/16",
                "notes": [
                    {"start_tick": 0, "length_tick": 1920, "pitch": 60, "velocity": 96, "channel": 0},
                    {"start_tick": 0, "length_tick": 1920, "pitch": 64, "velocity": 92, "channel": 0},
                    {"start_tick": 0, "length_tick": 1920, "pitch": 67, "velocity": 90, "channel": 0},
                    {"start_tick": 3840, "length_tick": 1920, "pitch": 62, "velocity": 94, "channel": 0},
                    {"start_tick": 3840, "length_tick": 1920, "pitch": 65, "velocity": 90, "channel": 0},
                    {"start_tick": 3840, "length_tick": 1920, "pitch": 69, "velocity": 88, "channel": 0},
                ],
                "program": 0,
                "is_drum": False,
                "ticks_per_beat": 960,
            },
        )
        self._timeline.add_clip(
            track1.track_id,
            "midi",
            start_bar=5,
            length_bars=4,
            name="Lead Hook",
            midi_data={
                "name": "Lead Hook",
                "bars": 4,
                "grid": "1/16",
                "notes": [
                    {"start_tick": 0, "length_tick": 480, "pitch": 72, "velocity": 104, "channel": 0},
                    {"start_tick": 960, "length_tick": 480, "pitch": 74, "velocity": 108, "channel": 0},
                    {"start_tick": 1920, "length_tick": 480, "pitch": 76, "velocity": 112, "channel": 0},
                    {"start_tick": 2880, "length_tick": 960, "pitch": 79, "velocity": 110, "channel": 0},
                    {"start_tick": 4320, "length_tick": 480, "pitch": 76, "velocity": 102, "channel": 0},
                    {"start_tick": 5280, "length_tick": 960, "pitch": 74, "velocity": 96, "channel": 0},
                ],
                "program": 0,
                "is_drum": False,
                "ticks_per_beat": 960,
            },
        )
        self._timeline.add_clip(track2.track_id, "audio", start_bar=1, length_bars=8, name="Drum Loop")

    def _track_signal_provider(self, track_id: str) -> list[float]:
        samples = self._waveforms.get_samples(track_id)
        if samples:
            return samples
        return _demo_signal_provider(track_id)

    def _mark_button_role(
        self,
        button: QPushButton,
        *,
        accent: bool = False,
        danger: bool = False,
    ) -> QPushButton:
        button.setProperty("accent", accent)
        button.setProperty("danger", danger)
        return button

    def _make_shell_badge(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("shellBadge", True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def _make_scroll_tab(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        return scroll

    def _setting_bool(self, key: str, default: bool) -> bool:
        if self._settings is None:
            return default
        value = self._settings.value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _setting_int(self, key: str, default: int) -> int:
        if self._settings is None:
            return default
        value = self._settings.value(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _setting_str(self, key: str, default: str) -> str:
        if self._settings is None:
            return default
        value = self._settings.value(key, default)
        return value if isinstance(value, str) else default

    def _write_setting(self, key: str, value: object) -> None:
        if self._settings is not None:
            self._settings.setValue(key, value)

    def _qml_path(self, filename: str) -> Path:
        return Path(__file__).resolve().parent / "qml" / filename

    def _build_quick_widget(
        self,
        filename: str,
        *,
        object_name: str,
        min_height: int,
        context: dict[str, object] | None = None,
    ) -> QWidget:
        if QQuickWidget is object:
            fallback = QLabel("Qt Quick unavailable")
            fallback.setObjectName(object_name)
            fallback.setMinimumHeight(min_height)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return fallback

        widget = QQuickWidget()
        widget.setObjectName(object_name)
        widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        widget.setClearColor(QColor("#16181D"))
        widget.setMinimumHeight(min_height)
        if context:
            for name, value in context.items():
                widget.rootContext().setContextProperty(name, value)
        path = self._qml_path(filename)
        widget.setSource(QUrl.fromLocalFile(str(path)))
        if widget.status() == QQuickWidget.Status.Error:
            errors = "\n".join(error.toString() for error in widget.errors())
            fallback = QLabel(f"Qt Quick load error\n{errors}")
            fallback.setObjectName(object_name)
            fallback.setMinimumHeight(min_height)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return fallback
        return widget

    def _current_display_mode(self) -> str:
        return self._workspace_layout.get_display_mode()

    def _sync_header_controls(self) -> None:
        mode_index = self.display_mode_combo.findData(self._workspace_layout.get_display_mode())
        if mode_index >= 0:
            self.display_mode_combo.blockSignals(True)
            self.display_mode_combo.setCurrentIndex(mode_index)
            self.display_mode_combo.blockSignals(False)

        self.toggle_inspector_button.blockSignals(True)
        self.toggle_inspector_button.setChecked(not self._workspace_layout.get_inspector_collapsed())
        self.toggle_inspector_button.setText(
            "インスペクタを隠す" if not self._workspace_layout.get_inspector_collapsed() else "インスペクタを表示"
        )
        self.toggle_inspector_button.blockSignals(False)

        self.toggle_rack_button.blockSignals(True)
        self.toggle_rack_button.setChecked(not self._workspace_layout.get_rack_collapsed())
        self.toggle_rack_button.setText(
            "下部ラックを隠す" if not self._workspace_layout.get_rack_collapsed() else "下部ラックを表示"
        )
        self.toggle_rack_button.blockSignals(False)

    def _apply_inspector_collapsed_state(self, collapsed: bool, *, persist: bool = True) -> None:
        self._workspace_layout.set_inspector_collapsed(collapsed)
        if hasattr(self, "inspector_panel"):
            if collapsed:
                sizes = self.workspace_body_splitter.sizes()
                if len(sizes) > 1 and sizes[1] > 0:
                    self._inspector_last_width = sizes[1]
                self.inspector_panel.hide()
                self.workspace_body_splitter.setSizes([1, 0])
            else:
                self.inspector_panel.show()
                self.workspace_body_splitter.setSizes([max(self.width() - self._inspector_last_width, 1), self._inspector_last_width])
        if persist:
            self._write_setting("workspace/inspector_collapsed", collapsed)
            self._write_setting("workspace/inspector_width", self._inspector_last_width)
        if hasattr(self, "toggle_inspector_button"):
            self._sync_header_controls()

    def _apply_rack_collapsed_state(self, collapsed: bool, *, persist: bool = True) -> None:
        self._workspace_layout.set_rack_collapsed(collapsed)
        if hasattr(self, "utility_rack"):
            if collapsed:
                sizes = self.workspace_splitter.sizes()
                if len(sizes) > 1 and sizes[1] > 0:
                    self._rack_last_height = sizes[1]
                self.utility_rack.hide()
                self.workspace_splitter.setSizes([1, 0])
            else:
                self.utility_rack.show()
                self.workspace_splitter.setSizes([max(self.height() - self._rack_last_height, 1), self._rack_last_height])
        if persist:
            self._write_setting("workspace/rack_collapsed", collapsed)
            self._write_setting("workspace/rack_height", self._rack_last_height)
        if hasattr(self, "toggle_rack_button"):
            self._sync_header_controls()

    def _toggle_inspector_panel(self) -> None:
        self._apply_inspector_collapsed_state(self.inspector_panel.isVisible())

    def _toggle_rack_panel(self) -> None:
        self._apply_rack_collapsed_state(self.utility_rack.isVisible())

    def _on_display_mode_changed(self, _index: int) -> None:
        current = self.display_mode_combo.currentData()
        mode = current if isinstance(current, str) else DISPLAY_MODE_BARS
        self._workspace_layout.set_display_mode(mode)
        self._write_setting("workspace/display_mode", mode)
        self._refresh_timeline_view()
        self._refresh_shell_state()

    def _on_arranger_zoom_changed(self, _index: int) -> None:
        current = self.arranger_zoom_combo.currentData()
        level = int(current) if isinstance(current, int) else 16
        self._workspace_layout.set_zoom_level(level)
        self._write_setting("workspace/zoom_level", level)
        self._refresh_timeline_view()

    def _sync_arranger_tool_controls(self) -> None:
        if not hasattr(self, "arranger_select_tool_button"):
            return
        self.arranger_select_tool_button.blockSignals(True)
        self.arranger_pencil_tool_button.blockSignals(True)
        self.arranger_select_tool_button.setChecked(self.tool_mode == "select")
        self.arranger_pencil_tool_button.setChecked(self.tool_mode == "pencil")
        self.arranger_select_tool_button.blockSignals(False)
        self.arranger_pencil_tool_button.blockSignals(False)

    def _set_tool_mode(self, tool_mode: str, *, persist: bool = True) -> None:
        normalized = tool_mode if tool_mode in {"select", "pencil"} else "select"
        if normalized == self.tool_mode:
            self._sync_arranger_tool_controls()
            return
        self.tool_mode = normalized
        self._timeline_scene_model.set_tool_mode(normalized)
        if persist:
            self._write_setting("workspace/tool_mode", normalized)
        self._sync_arranger_tool_controls()
        self._refresh_timeline_view()

    def _step_arranger_zoom(self, direction: int) -> None:
        current_level = self._workspace_layout.get_zoom_level()
        try:
            current_index = self._arranger_zoom_levels.index(current_level)
        except ValueError:
            current_index = self._arranger_zoom_levels.index(16)
        next_index = min(max(current_index + direction, 0), len(self._arranger_zoom_levels) - 1)
        self.arranger_zoom_combo.setCurrentIndex(next_index)

    def _on_arranger_zoom_in(self) -> None:
        self._step_arranger_zoom(1)

    def _on_arranger_zoom_out(self) -> None:
        self._step_arranger_zoom(-1)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appShell")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        root_layout.addWidget(self._build_shell_panel())

        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.addWidget(self._build_workspace_area())
        self.utility_rack = self._build_utility_rack()
        self.workspace_splitter.addWidget(self.utility_rack)
        self.workspace_splitter.setSizes([580, 360])
        root_layout.addWidget(self.workspace_splitter, 1)

        self.setCentralWidget(root)
        self.setStyleSheet(_studio_one_stylesheet())
        self._on_compose_part_changed()
        self._sync_phrase_range_with_bars()
        self._refresh_compose_ab_label()
        self._refresh_compose_history()
        self._refresh_history()
        self._clear_pitch_display()
        self._sync_header_controls()
        self._sync_arranger_tool_controls()
        self._apply_inspector_collapsed_state(self._workspace_layout.get_inspector_collapsed(), persist=False)
        self._apply_rack_collapsed_state(self._workspace_layout.get_rack_collapsed(), persist=False)
        self._refresh_shell_state()

    def _build_shell_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("transportBar")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.transport_title_label = QLabel("music-create")
        self.transport_title_label.setObjectName("shellTitle")
        self.transport_subtitle_label = QLabel("Production Workspace")
        self.transport_subtitle_label.setObjectName("shellSubtitle")
        title_col.addWidget(self.transport_title_label)
        title_col.addWidget(self.transport_subtitle_label)
        top_row.addLayout(title_col)
        top_row.addStretch(1)

        self.playback_badge = self._make_shell_badge("PLAYBACK READY")
        self.track_badge = self._make_shell_badge("TRACK track-1")
        self.mix_engine_badge = self._make_shell_badge("MIX RULE / QUICK")
        self.compose_engine_badge = self._make_shell_badge("COMPOSE RULE / 1/16")
        for badge in (
            self.playback_badge,
            self.track_badge,
            self.mix_engine_badge,
            self.compose_engine_badge,
        ):
            top_row.addWidget(badge)
        layout.addLayout(top_row)

        control_row = QHBoxLayout()
        control_row.setSpacing(8)
        mode_label = QLabel("表示単位")
        mode_label.setObjectName("panelCaption")
        control_row.addWidget(mode_label)
        self.display_mode_combo = QComboBox()
        self.display_mode_combo.addItem("小節", DISPLAY_MODE_BARS)
        self.display_mode_combo.addItem("時間", DISPLAY_MODE_TIME)
        control_row.addWidget(self.display_mode_combo)
        control_row.addStretch(1)
        self.toggle_inspector_button = QPushButton("インスペクタ")
        self.toggle_inspector_button.setCheckable(True)
        self.toggle_rack_button = QPushButton("下部ラック")
        self.toggle_rack_button.setCheckable(True)
        control_row.addWidget(self.toggle_inspector_button)
        control_row.addWidget(self.toggle_rack_button)
        layout.addLayout(control_row)

        self.transport_view = self._build_quick_widget(
            "TransportStrip.qml",
            object_name="transportQuick",
            min_height=78,
            context={"transportState": self._transport_state},
        )
        layout.addWidget(self.transport_view)

        self.status_label = QLabel("[--:--:--] 準備完了。")
        self.status_label.setObjectName("statusStrip")
        layout.addWidget(self.status_label)
        self.display_mode_combo.currentIndexChanged.connect(self._on_display_mode_changed)
        self.toggle_inspector_button.clicked.connect(self._toggle_inspector_panel)
        self.toggle_rack_button.clicked.connect(self._toggle_rack_panel)
        return panel

    def _build_workspace_area(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.workspace_body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_body_splitter.setChildrenCollapsible(False)
        self.arranger_panel = self._build_arranger_panel()
        self.inspector_panel = self._build_inspector_panel()
        self.workspace_body_splitter.addWidget(self.arranger_panel)
        self.workspace_body_splitter.addWidget(self.inspector_panel)
        self.workspace_body_splitter.setSizes([1140, 360])

        layout.addWidget(self.workspace_body_splitter, 1)
        return page

    def _build_arranger_panel(self) -> QGroupBox:
        box = QGroupBox("アレンジャー")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.arranger_context_label = QLabel("Timeline minimap / lanes / clip view")
        self.arranger_context_label.setObjectName("panelCaption")
        toolbar.addWidget(self.arranger_context_label)
        toolbar.addStretch(1)

        self.arranger_select_tool_button = QPushButton("選択")
        self.arranger_select_tool_button.setCheckable(True)
        self.arranger_pencil_tool_button = QPushButton("鉛筆")
        self.arranger_pencil_tool_button.setCheckable(True)
        self.add_track_button = QPushButton("トラック追加")
        self.add_midi_clip_button = QPushButton("MIDI追加")
        self.add_audio_clip_button = QPushButton("Audio追加")
        self.arranger_zoom_out_button = QPushButton("-")
        self.arranger_zoom_in_button = QPushButton("+")
        self.arranger_zoom_combo = QComboBox()
        for level in self._arranger_zoom_levels:
            self.arranger_zoom_combo.addItem(f"{level} px/bar", level)
        zoom_index = self.arranger_zoom_combo.findData(self._workspace_layout.get_zoom_level())
        self.arranger_zoom_combo.setCurrentIndex(zoom_index if zoom_index >= 0 else 2)
        for button in (
            self.arranger_select_tool_button,
            self.arranger_pencil_tool_button,
            self.add_track_button,
            self.add_midi_clip_button,
            self.add_audio_clip_button,
            self.arranger_zoom_out_button,
        ):
            toolbar.addWidget(button)
        toolbar.addWidget(self.arranger_zoom_combo)
        toolbar.addWidget(self.arranger_zoom_in_button)
        layout.addLayout(toolbar)

        self.arranger_view = self._build_quick_widget(
            "ArrangerCanvas.qml",
            object_name="arrangerQuick",
            min_height=480,
            context={"sceneModel": self._timeline_scene_model},
        )
        layout.addWidget(self.arranger_view, 1)

        self.add_track_button.clicked.connect(self._on_add_track)
        self.add_midi_clip_button.clicked.connect(lambda: self._on_add_clip("midi"))
        self.add_audio_clip_button.clicked.connect(lambda: self._on_add_clip("audio"))
        self.arranger_select_tool_button.clicked.connect(lambda: self._set_tool_mode("select"))
        self.arranger_pencil_tool_button.clicked.connect(lambda: self._set_tool_mode("pencil"))
        self.arranger_zoom_out_button.clicked.connect(self._on_arranger_zoom_out)
        self.arranger_zoom_in_button.clicked.connect(self._on_arranger_zoom_in)
        self.arranger_zoom_combo.currentIndexChanged.connect(self._on_arranger_zoom_changed)
        return box

    def _build_editor_panel(self) -> QWidget:
        box = QWidget()
        box.setMinimumHeight(620)
        layout = QHBoxLayout(box)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(12)

        sidebar = QWidget()
        sidebar.setMinimumWidth(340)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)

        self.pitch_clip_label = QLabel("選択MIDIクリップ: なし")
        self.pitch_clip_label.setObjectName("panelHeadline")
        sidebar_layout.addWidget(self.pitch_clip_label)

        clip_summary_label = QLabel("クリップ概要")
        clip_summary_label.setObjectName("sectionLabel")
        sidebar_layout.addWidget(clip_summary_label)

        self.editor_clip_summary = QTextEdit()
        self.editor_clip_summary.setReadOnly(True)
        self.editor_clip_summary.setMinimumHeight(130)
        self.editor_clip_summary.setPlaceholderText("選択クリップの概要をここに表示します。")
        sidebar_layout.addWidget(self.editor_clip_summary)

        pitch_label = QLabel("音階 / ノート")
        pitch_label.setObjectName("sectionLabel")
        sidebar_layout.addWidget(pitch_label)

        self.pitch_detail = QTextEdit()
        self.pitch_detail.setReadOnly(True)
        self.pitch_detail.setMinimumHeight(110)
        self.pitch_detail.setPlaceholderText("MIDIクリップを選択するとノート情報を表示します。")
        sidebar_layout.addWidget(self.pitch_detail, 1)

        edit_form = QFormLayout()
        self.midi_edit_instrument_combo = QComboBox()
        for label, program in composition_instrument_options():
            self.midi_edit_instrument_combo.addItem(f"{label} ({program})", program)
        self.midi_transpose_spin = QSpinBox()
        self.midi_transpose_spin.setRange(-24, 24)
        self.midi_transpose_spin.setValue(0)
        edit_form.addRow("楽器", self.midi_edit_instrument_combo)
        edit_form.addRow("半音シフト", self.midi_transpose_spin)
        sidebar_layout.addLayout(edit_form)

        edit_buttons = QHBoxLayout()
        self.midi_apply_edit_button = QPushButton("編集を反映")
        self.midi_preview_button = QPushButton("選択MIDI試聴")
        self._mark_button_role(self.midi_apply_edit_button, accent=True)
        edit_buttons.addWidget(self.midi_apply_edit_button)
        edit_buttons.addWidget(self.midi_preview_button)
        sidebar_layout.addLayout(edit_buttons)

        roll_container = QWidget()
        roll_layout = QVBoxLayout(roll_container)
        roll_layout.setContentsMargins(0, 0, 0, 0)
        roll_layout.setSpacing(8)
        waveform_caption = QLabel("Waveform")
        waveform_caption.setObjectName("sectionLabel")
        roll_layout.addWidget(waveform_caption)
        self.waveform_view = WaveformView()
        self.waveform_view.setMinimumHeight(130)
        roll_layout.addWidget(self.waveform_view)
        roll_caption = QLabel("Piano Roll")
        roll_caption.setObjectName("sectionLabel")
        roll_layout.addWidget(roll_caption)
        self.piano_roll_view = SimplePianoRollView()
        self.piano_roll_view.setObjectName("pianoRollEditor")
        self.piano_roll_view.setMinimumHeight(280)
        roll_layout.addWidget(self.piano_roll_view, 1)

        layout.addWidget(sidebar, 0)
        layout.addWidget(roll_container, 1)

        self.midi_apply_edit_button.clicked.connect(self._on_apply_midi_edit)
        self.midi_preview_button.clicked.connect(self._on_preview_selected_midi)
        return box

    def _build_inspector_panel(self) -> QGroupBox:
        box = QGroupBox("インスペクタ")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(10)

        self.inspector_tabs = QTabWidget()
        self.inspector_tabs.addTab(self._make_scroll_tab(self._build_track_inspector_tab()), "トラック")
        self.inspector_tabs.addTab(self._make_scroll_tab(self._build_compose_inspector_tab()), "作曲")
        self.inspector_tabs.addTab(self._make_scroll_tab(self._build_mix_inspector_tab()), "ミックス")
        layout.addWidget(self.inspector_tabs, 1)
        return box

    def _build_track_inspector_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        header = QLabel("Track source / playback")
        header.setObjectName("panelCaption")
        layout.addWidget(header)

        form = QFormLayout()
        self.track_input = QLineEdit("track-1")
        form.addRow("トラックID", self.track_input)
        layout.addLayout(form)

        wav_row = QHBoxLayout()
        wav_row.setSpacing(8)
        self.load_wav_button = QPushButton("WAV読込")
        self.play_wav_button = QPushButton("再生")
        self.stop_wav_button = QPushButton("停止")
        self._mark_button_role(self.play_wav_button, accent=True)
        wav_row.addWidget(self.load_wav_button)
        wav_row.addWidget(self.play_wav_button)
        wav_row.addWidget(self.stop_wav_button)
        layout.addLayout(wav_row)

        self.wav_info_label = QLabel("WAV未読込")
        self.wav_info_label.setObjectName("transportMetric")
        layout.addWidget(self.wav_info_label)

        self.track_playback_position_label = QLabel("再生位置: bar 1.00 / 0.00s")
        self.track_playback_position_label.setObjectName("transportMetric")
        layout.addWidget(self.track_playback_position_label)

        clip_label = QLabel("選択クリップ")
        clip_label.setObjectName("sectionLabel")
        layout.addWidget(clip_label)

        self.track_clip_summary = QTextEdit()
        self.track_clip_summary.setReadOnly(True)
        self.track_clip_summary.setMinimumHeight(180)
        self.track_clip_summary.setPlaceholderText("選択クリップの概要をここに表示します。")
        layout.addWidget(self.track_clip_summary)
        layout.addStretch(1)

        self.track_input.editingFinished.connect(self._on_track_input_edited)
        self.load_wav_button.clicked.connect(self._on_load_wav)
        self.play_wav_button.clicked.connect(self._on_play_wav)
        self.stop_wav_button.clicked.connect(self._on_stop_wav)
        return page

    def _build_mix_inspector_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        header = QLabel("Mix analysis / suggestion")
        header.setObjectName("panelCaption")
        layout.addWidget(header)

        form = QFormLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("クリーン", "clean")
        self.profile_combo.addItem("パンチ", "punch")
        self.profile_combo.addItem("ウォーム", "warm")
        self.suggestion_engine_combo = QComboBox()
        self.suggestion_engine_combo.addItem("ルールベース", "rule-based")
        self.suggestion_engine_combo.addItem("LLMベース", "llm-based")
        current_engine = self._mixing.get_suggestion_mode()
        self.suggestion_engine_combo.setCurrentIndex(0 if current_engine == "rule-based" else 1)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("高速（quick）", "quick")
        self.mode_combo.addItem("詳細（full）", "full")
        form.addRow("プロファイル", self.profile_combo)
        form.addRow("提案エンジン", self.suggestion_engine_combo)
        form.addRow("解析モード", self.mode_combo)
        layout.addLayout(form)

        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("Dry/Wet"))
        self.dry_wet_slider = QSlider(Qt.Orientation.Horizontal)
        self.dry_wet_slider.setRange(0, 100)
        self.dry_wet_slider.setValue(100)
        self.dry_wet_label = QLabel("100%")
        slider_row.addWidget(self.dry_wet_slider, 1)
        slider_row.addWidget(self.dry_wet_label)
        layout.addLayout(slider_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.analyze_button = QPushButton("解析")
        self.suggest_button = QPushButton("提案")
        self.preview_button = QPushButton("試聴")
        self.cancel_preview_button = QPushButton("試聴取消")
        self.apply_button = QPushButton("適用")
        self.revert_button = QPushButton("巻き戻し")
        self._mark_button_role(self.analyze_button, accent=True)
        self._mark_button_role(self.suggest_button, accent=True)
        self._mark_button_role(self.apply_button, accent=True)
        self._mark_button_role(self.revert_button, danger=True)
        for btn in (
            self.analyze_button,
            self.suggest_button,
            self.preview_button,
            self.cancel_preview_button,
            self.apply_button,
            self.revert_button,
        ):
            action_row.addWidget(btn)
        layout.addLayout(action_row)
        layout.addStretch(1)

        self.analyze_button.clicked.connect(self._on_analyze)
        self.suggest_button.clicked.connect(self._on_suggest)
        self.preview_button.clicked.connect(self._on_preview)
        self.cancel_preview_button.clicked.connect(self._on_cancel_preview)
        self.apply_button.clicked.connect(self._on_apply)
        self.revert_button.clicked.connect(self._on_revert)
        self.dry_wet_slider.valueChanged.connect(self._on_dry_wet_changed)
        self.suggestion_engine_combo.currentIndexChanged.connect(self._on_suggestion_engine_changed)
        self.suggestion_engine_combo.currentIndexChanged.connect(self._refresh_shell_state)
        self.mode_combo.currentIndexChanged.connect(self._refresh_shell_state)
        return page

    def _build_compose_inspector_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        header = QLabel("Compose generation / timeline insert")
        header.setObjectName("panelCaption")
        layout.addWidget(header)

        form = QFormLayout()
        self.compose_track_input = QLineEdit("track-1")
        self.compose_part_combo = QComboBox()
        self.compose_part_combo.addItem("コード", "chord")
        self.compose_part_combo.addItem("メロディ", "melody")
        self.compose_part_combo.addItem("ドラム", "drum")
        self.compose_key_combo = QComboBox()
        for key in ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"):
            self.compose_key_combo.addItem(key, key)
        self.compose_scale_combo = QComboBox()
        self.compose_scale_combo.addItem("メジャー", "major")
        self.compose_scale_combo.addItem("マイナー", "minor")
        self.compose_style_combo = QComboBox()
        self.compose_style_combo.addItem("ポップ", "pop")
        self.compose_style_combo.addItem("ロック", "rock")
        self.compose_style_combo.addItem("ヒップホップ", "hiphop")
        self.compose_style_combo.addItem("EDM", "edm")
        self.compose_style_combo.addItem("バラード", "ballad")
        self.compose_grid_combo = QComboBox()
        for grid in composition_grid_options():
            self.compose_grid_combo.addItem(grid, grid)
        self.compose_grid_combo.setCurrentText("1/16")
        self.compose_bars_spin = QSpinBox()
        self.compose_bars_spin.setRange(1, 32)
        self.compose_bars_spin.setValue(4)
        self.compose_phrase_from_spin = QSpinBox()
        self.compose_phrase_from_spin.setRange(1, 32)
        self.compose_phrase_from_spin.setValue(1)
        self.compose_phrase_to_spin = QSpinBox()
        self.compose_phrase_to_spin.setRange(1, 32)
        self.compose_phrase_to_spin.setValue(4)
        self.compose_instrument_combo = QComboBox()
        for label, program in composition_instrument_options():
            self.compose_instrument_combo.addItem(f"{label} (Program {program})", program)
        self.compose_engine_combo = QComboBox()
        self.compose_engine_combo.addItem("ルールベース", "rule-based")
        self.compose_engine_combo.addItem("LLMベース", "llm-based")
        self.compose_engine_combo.setCurrentIndex(0 if self._composition.get_engine() == "rule-based" else 1)

        form.addRow("挿入トラックID", self.compose_track_input)
        form.addRow("パート", self.compose_part_combo)
        form.addRow("キー", self.compose_key_combo)
        form.addRow("スケール", self.compose_scale_combo)
        form.addRow("スタイル", self.compose_style_combo)
        form.addRow("グリッド", self.compose_grid_combo)
        form.addRow("小節数", self.compose_bars_spin)
        form.addRow("部分開始", self.compose_phrase_from_spin)
        form.addRow("部分終了", self.compose_phrase_to_spin)
        form.addRow("楽器", self.compose_instrument_combo)
        form.addRow("提案エンジン", self.compose_engine_combo)
        layout.addLayout(form)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.compose_suggest_button = QPushButton("作曲提案")
        self.compose_preview_button = QPushButton("作曲試聴")
        self.compose_apply_button = QPushButton("タイムライン挿入")
        self.compose_revert_button = QPushButton("挿入を巻き戻し")
        self._mark_button_role(self.compose_suggest_button, accent=True)
        self._mark_button_role(self.compose_apply_button, accent=True)
        self._mark_button_role(self.compose_revert_button, danger=True)
        for btn in (
            self.compose_suggest_button,
            self.compose_preview_button,
            self.compose_apply_button,
            self.compose_revert_button,
        ):
            action_row.addWidget(btn)
        layout.addLayout(action_row)
        layout.addStretch(1)

        self.compose_part_combo.currentIndexChanged.connect(self._on_compose_part_changed)
        self.compose_part_combo.currentIndexChanged.connect(self._refresh_shell_state)
        self.compose_track_input.editingFinished.connect(self._refresh_compose_history)
        self.compose_track_input.textChanged.connect(self._refresh_shell_state)
        self.compose_bars_spin.valueChanged.connect(self._sync_phrase_range_with_bars)
        self.compose_phrase_from_spin.valueChanged.connect(self._normalize_phrase_range)
        self.compose_phrase_to_spin.valueChanged.connect(self._normalize_phrase_range)
        self.compose_suggest_button.clicked.connect(self._on_compose_suggest)
        self.compose_preview_button.clicked.connect(self._on_compose_preview)
        self.compose_apply_button.clicked.connect(self._on_compose_apply)
        self.compose_revert_button.clicked.connect(self._on_compose_revert)
        self.compose_engine_combo.currentIndexChanged.connect(self._refresh_shell_state)
        self.compose_grid_combo.currentIndexChanged.connect(self._refresh_shell_state)
        return page

    def _build_utility_rack(self) -> QGroupBox:
        box = QGroupBox("ユーティリティラック")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(10)

        self.utility_tabs = QTabWidget()
        self.editor_panel = self._build_editor_panel()
        self.editor_scroll_area = self._make_scroll_tab(self.editor_panel)
        self.editor_scroll_area.setObjectName("editorScrollArea")
        self.editor_tab = self.editor_scroll_area
        self.utility_tabs.addTab(self.editor_tab, "エディタ")
        self.utility_tabs.addTab(self._build_mix_suggestion_tab(), "ミックス提案")
        self.utility_tabs.addTab(self._build_mix_history_tab(), "ミックス履歴")
        self.utility_tabs.addTab(self._build_compose_suggestion_tab(), "作曲提案")
        self.compose_compare_tab = self._build_compose_compare_tab()
        self.utility_tabs.addTab(self.compose_compare_tab, "A/B比較")
        self.compose_history_tab = self._build_compose_history_tab()
        self.utility_tabs.addTab(self.compose_history_tab, "作曲履歴")
        layout.addWidget(self.utility_tabs, 1)
        return box

    def _build_mix_suggestion_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.analysis_summary = QTextEdit()
        self.analysis_summary.setReadOnly(True)
        self.analysis_summary.setMinimumHeight(120)
        self.analysis_summary.setMaximumHeight(160)
        self.analysis_summary.setPlaceholderText("解析結果をここに表示します。")
        layout.addWidget(self.analysis_summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.suggestion_list = QListWidget()
        self.suggestion_list.currentItemChanged.connect(self._on_suggestion_selected)
        self.suggestion_detail = QTextEdit()
        self.suggestion_detail.setReadOnly(True)
        self.suggestion_detail.setPlaceholderText("提案詳細をここに表示します。")
        splitter.addWidget(self.suggestion_list)
        splitter.addWidget(self.suggestion_detail)
        splitter.setSizes([360, 760])
        layout.addWidget(splitter, 1)
        return page

    def _build_mix_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.history_list = QListWidget()
        self.history_list.currentItemChanged.connect(self._on_history_selected)
        self.history_detail = QTextEdit()
        self.history_detail.setReadOnly(True)
        self.history_detail.setPlaceholderText("履歴詳細をここに表示します。")
        splitter.addWidget(self.history_list)
        splitter.addWidget(self.history_detail)
        splitter.setSizes([360, 760])
        layout.addWidget(splitter, 1)
        return page

    def _build_compose_suggestion_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_label = QLabel("選択候補を A/B スロットへ送る")
        action_label.setObjectName("panelCaption")
        self.compose_set_a_button = QPushButton("選択をA")
        self.compose_set_b_button = QPushButton("選択をB")
        self._mark_button_role(self.compose_set_a_button, accent=True)
        self._mark_button_role(self.compose_set_b_button, accent=True)
        action_row.addWidget(action_label)
        action_row.addStretch(1)
        action_row.addWidget(self.compose_set_a_button)
        action_row.addWidget(self.compose_set_b_button)
        layout.addLayout(action_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.compose_suggestion_list = QListWidget()
        self.compose_suggestion_list.setToolTip("作曲提案候補（スコア順）")
        self.compose_detail = QTextEdit()
        self.compose_detail.setReadOnly(True)
        self.compose_detail.setPlaceholderText("作曲提案の詳細をここに表示します。")
        splitter.addWidget(self.compose_suggestion_list)
        splitter.addWidget(self.compose_detail)
        splitter.setSizes([360, 760])
        layout.addWidget(splitter, 1)

        self.compose_set_a_button.clicked.connect(self._on_set_compose_ab_a)
        self.compose_set_b_button.clicked.connect(self._on_set_compose_ab_b)
        self.compose_suggestion_list.currentItemChanged.connect(self._on_compose_suggestion_selected)
        return page

    def _build_compose_compare_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        self.compose_ab_label = QLabel("A: 未設定 / B: 未設定")
        self.compose_ab_label.setObjectName("panelHeadline")
        self.compose_preview_a_button = QPushButton("A試聴")
        self.compose_preview_b_button = QPushButton("B試聴")
        self.compose_compare_button = QPushButton("比較を更新")
        self._mark_button_role(self.compose_compare_button, accent=True)
        header_row.addWidget(self.compose_ab_label, 1)
        header_row.addWidget(self.compose_preview_a_button)
        header_row.addWidget(self.compose_preview_b_button)
        header_row.addWidget(self.compose_compare_button)
        layout.addLayout(header_row)

        self.compose_compare_detail = QTextEdit()
        self.compose_compare_detail.setReadOnly(True)
        self.compose_compare_detail.setPlaceholderText("A/B比較結果をここに表示します。")
        layout.addWidget(self.compose_compare_detail, 1)

        self.compose_preview_a_button.clicked.connect(self._on_compose_preview_a)
        self.compose_preview_b_button.clicked.connect(self._on_compose_preview_b)
        self.compose_compare_button.clicked.connect(self._on_compose_compare_ab)
        return page

    def _build_compose_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.compose_history_list = QListWidget()
        self.compose_history_list.setToolTip("作曲タイムライン挿入履歴")
        self.compose_history_detail = QTextEdit()
        self.compose_history_detail.setReadOnly(True)
        self.compose_history_detail.setPlaceholderText("作曲挿入履歴の詳細をここに表示します。")
        splitter.addWidget(self.compose_history_list)
        splitter.addWidget(self.compose_history_detail)
        splitter.setSizes([360, 760])
        layout.addWidget(splitter, 1)

        self.compose_history_list.currentItemChanged.connect(self._on_compose_history_selected)
        return page

    def _configure_timeline_table(self) -> None:
        return None

    def _sync_track_controls_from_timeline(self) -> None:
        current = self.track_input.text().strip()
        tracks = self._timeline.tracks_in_order()
        if not tracks:
            self.track_input.setText("track-1")
            if hasattr(self, "compose_track_input"):
                self.compose_track_input.setText("track-1")
            return
        if current not in self._timeline.tracks:
            self.track_input.setText(tracks[0].track_id)
        if hasattr(self, "compose_track_input"):
            compose_current = self.compose_track_input.text().strip()
            if compose_current not in self._timeline.tracks:
                self.compose_track_input.setText(self.track_input.text().strip())
        self._selected_timeline_bar = min(max(self._selected_timeline_bar, 1), self._timeline.bars)
        self._refresh_shell_state()

    def _on_track_input_edited(self) -> None:
        track_id = self._current_track_id()
        self.selected_clip_id = None
        if hasattr(self, "compose_track_input") and track_id in self._timeline.tracks:
            self.compose_track_input.setText(track_id)
        self._refresh_wav_info()
        self._refresh_history()
        self._paint_playhead()
        self._update_pitch_display(track_id=track_id, bar=self._selected_timeline_bar)
        self._refresh_shell_state()

    def _set_selected_clip_summary(
        self,
        clip: TimelineClip | None,
        raw: dict[str, object] | None = None,
    ) -> None:
        if clip is None:
            text = "選択クリップ: なし\nタイムラインでクリップを選択すると概要を表示します。"
        else:
            track = self._timeline.tracks.get(clip.track_id)
            lines = [
                f"選択クリップ: {clip.name}",
                f"タイプ: {'MIDI' if clip.clip_type == 'midi' else 'Audio'}",
                f"トラック: {clip.track_id}",
            ]
            if track is not None:
                lines.append(f"楽器: {track.instrument_name}")
            lines.append(
                "範囲: "
                + format_clip_range(
                    clip.start_bar,
                    clip.end_bar,
                    display_mode=self._current_display_mode(),
                    tempo_bpm=self._tempo_bpm,
                    beats_per_bar=self._beats_per_bar,
                )
                + (f" ({clip.length_bars} bars)" if self._current_display_mode() == DISPLAY_MODE_TIME else "")
            )
            if clip.clip_type == "midi" and isinstance(raw, dict):
                notes = raw.get("notes")
                note_count = len(notes) if isinstance(notes, list) else 0
                lines.append(f"ノート数: {note_count}")
                grid = raw.get("grid")
                if isinstance(grid, str):
                    lines.append(f"グリッド: {grid}")
                program = raw.get("program")
                if bool(raw.get("is_drum")):
                    lines.append("楽器: ドラム")
                elif isinstance(program, int):
                    lines.append(f"楽器Program: {program}")
            elif clip.clip_type == "audio":
                wav = self._waveforms.get_item(clip.track_id)
                if wav is not None:
                    lines.append(f"WAV: {wav.path.name}")
                    lines.append(f"長さ: {wav.duration_sec:.2f}s @ {wav.sample_rate}Hz")
            text = "\n".join(lines)

        if hasattr(self, "editor_clip_summary"):
            self.editor_clip_summary.setPlainText(text)
        if hasattr(self, "track_clip_summary"):
            self.track_clip_summary.setPlainText(text)

    def _refresh_playback_position_labels(self) -> None:
        elapsed = self._bar_to_seconds(self._timeline.playhead_bar)
        transport_text = format_transport_position(
            self._timeline.playhead_bar,
            display_mode=self._current_display_mode(),
            tempo_bpm=self._tempo_bpm,
            beats_per_bar=self._beats_per_bar,
        )
        if hasattr(self, "track_playback_position_label"):
            if self._current_display_mode() == DISPLAY_MODE_TIME:
                self.track_playback_position_label.setText(
                    f"再生位置: {transport_text} / {format_clock_time(elapsed, always_include_hours=False, include_millis=True)}"
                )
            else:
                self.track_playback_position_label.setText(
                    f"再生位置: {transport_text} / {elapsed:.2f}s"
                )

    def _refresh_shell_state(self, _value: object | None = None) -> None:
        if not hasattr(self, "playback_badge"):
            return
        mix_engine = "LLM" if self._current_suggestion_engine() == "llm-based" else "RULE"
        mix_mode = self._current_mode().upper()
        compose_engine = "LLM" if self._current_compose_engine() == "llm-based" else "RULE"
        current_track = self._current_track_id()
        if self._playback_started_at is not None and self._playback_track_id is not None:
            playback_text = f"PLAYING {self._playback_track_id} {self._playback_elapsed_sec:0.1f}s"
        else:
            playback_text = "PLAYBACK READY"
        self.playback_badge.setText(playback_text)
        self.track_badge.setText(f"TRACK {current_track}")
        self.mix_engine_badge.setText(f"MIX {mix_engine} / {mix_mode}")
        self.compose_engine_badge.setText(f"COMPOSE {compose_engine} / {self._current_compose_grid()}")
        self._transport_state.sync(
            playhead_bar=self._timeline.playhead_bar,
            total_bars=self._timeline.bars,
            display_mode=self._current_display_mode(),
            tempo_bpm=self._tempo_bpm,
            beats_per_bar=self._beats_per_bar,
        )
        self._refresh_playback_position_labels()

    def _refresh_timeline_view(self) -> None:
        if self.selected_clip_id is not None and self.selected_clip_id not in self._timeline.clips:
            self.selected_clip_id = None
        tracks_data: list[dict[str, object]] = []
        for track in self._timeline.tracks_in_order():
            clips: list[dict[str, object]] = []
            for clip in self._timeline.clips_for_track(track.track_id):
                clip_color = track.color if clip.clip_type == "midi" else "#D97A36"
                clips.append(
                    {
                        "clipId": clip.clip_id,
                        "trackId": clip.track_id,
                        "name": clip.name,
                        "clipType": clip.clip_type,
                        "startBar": clip.start_bar,
                        "lengthBars": clip.length_bars,
                        "endBar": clip.end_bar,
                        "color": clip_color,
                        "tooltip": (
                            f"{clip.name} | {'MIDI' if clip.clip_type == 'midi' else 'Audio'} | "
                            + format_clip_range(
                                clip.start_bar,
                                clip.end_bar,
                                display_mode=self._current_display_mode(),
                                tempo_bpm=self._tempo_bpm,
                                beats_per_bar=self._beats_per_bar,
                            )
                        ),
                    }
                )
            tracks_data.append(
                {
                    "trackId": track.track_id,
                    "name": track.name,
                    "instrumentName": track.instrument_name,
                    "program": track.program,
                    "isDrum": track.is_drum,
                    "color": track.color,
                    "clips": clips,
                }
            )

        self._timeline.refresh_content_end_bar()
        self._timeline_scene_model.sync(
            tracks=tracks_data,
            total_bars=self._timeline.bars,
            content_end_bar=self._timeline.content_end_bar,
            max_bars=self._timeline.max_bars,
            playhead_bar=self._timeline.playhead_bar,
            selected_track_id=self._current_track_id(),
            selected_bar=self._selected_timeline_bar,
            selected_clip_id=self.selected_clip_id or "",
            zoom_level=self._workspace_layout.get_zoom_level(),
            display_mode=self._current_display_mode(),
            tempo_bpm=self._tempo_bpm,
            beats_per_bar=self._beats_per_bar,
            tool_mode=self.tool_mode,
        )
        self._paint_playhead()
        if hasattr(self, "pitch_detail"):
            self._update_pitch_display(
                track_id=self._current_track_id(),
                bar=self._selected_timeline_bar,
                clip_id=self.selected_clip_id,
            )

    def _paint_playhead(self) -> None:
        self._refresh_playback_position_labels()
        self._transport_state.sync(
            playhead_bar=self._timeline.playhead_bar,
            total_bars=self._timeline.bars,
            display_mode=self._current_display_mode(),
            tempo_bpm=self._tempo_bpm,
            beats_per_bar=self._beats_per_bar,
        )
        self._timeline_scene_model.sync(
            tracks=self._timeline_scene_model.get_tracks(),
            total_bars=self._timeline.bars,
            content_end_bar=self._timeline.content_end_bar,
            max_bars=self._timeline.max_bars,
            playhead_bar=self._timeline.playhead_bar,
            selected_track_id=self._current_track_id(),
            selected_bar=self._selected_timeline_bar,
            selected_clip_id=self.selected_clip_id or "",
            zoom_level=self._workspace_layout.get_zoom_level(),
            display_mode=self._current_display_mode(),
            tempo_bpm=self._tempo_bpm,
            beats_per_bar=self._beats_per_bar,
            tool_mode=self.tool_mode,
        )
        self._refresh_waveform_playhead()

    def _on_playhead_changed(self, value: int) -> None:
        self._set_playhead_bar(value / 100.0)

    def _set_playhead_bar(self, bar: float, update_slider: bool = True) -> None:
        self._timeline.set_playhead_bar(bar)
        self._paint_playhead()

    def _seconds_per_bar(self) -> float:
        return seconds_per_bar(self._tempo_bpm, self._beats_per_bar)

    def _seconds_to_bar(self, elapsed_sec: float) -> float:
        return seconds_to_bar(elapsed_sec, self._tempo_bpm, self._beats_per_bar)

    def _bar_to_seconds(self, bar: float) -> float:
        return bar_to_seconds(bar, self._tempo_bpm, self._beats_per_bar)

    def _playhead_ratio_for_track(self, track_id: str) -> float:
        item = self._waveforms.get_item(track_id)
        if item is None or item.duration_sec <= 0:
            return 0.0
        sec = self._bar_to_seconds(self._timeline.playhead_bar)
        return min(max(sec / item.duration_sec, 0.0), 1.0)

    def _refresh_waveform_playhead(self) -> None:
        track_id = self._current_track_id()
        if (
            self._playback_track_id == track_id
            and self._playback_duration_sec > 0.0
            and self._playback_started_at is not None
        ):
            ratio = min(max(self._playback_elapsed_sec / self._playback_duration_sec, 0.0), 1.0)
            self.waveform_view.set_playhead_ratio(ratio)
            return
        self.waveform_view.set_playhead_ratio(self._playhead_ratio_for_track(track_id))

    def _refresh_waveform_view(self) -> None:
        track_id = self._current_track_id()
        item = self._waveforms.get_item(track_id)
        if item is None:
            self.waveform_view.clear()
            self._refresh_shell_state()
            return
        self.waveform_view.set_waveform(item.samples, item.duration_sec)
        self.waveform_view.set_playhead_ratio(self._playhead_ratio_for_track(track_id))
        self._refresh_shell_state()

    def _clear_pitch_display(self, keep_clip_summary: bool = False) -> None:
        self._selected_midi_clip_id = None
        self.pitch_clip_label.setText("選択MIDIクリップ: なし")
        self.pitch_detail.setPlainText("音階: -")
        self.piano_roll_view.clear()
        self.piano_roll_view.set_editable(False, None)
        if not keep_clip_summary:
            self._set_selected_clip_summary(None)
        self._set_midi_edit_enabled(False)

    def _set_midi_edit_enabled(self, enabled: bool, is_drum: bool = False) -> None:
        self.midi_transpose_spin.setEnabled(enabled)
        self.midi_apply_edit_button.setEnabled(enabled)
        self.midi_preview_button.setEnabled(enabled)
        self.midi_edit_instrument_combo.setEnabled(enabled and (not is_drum))

    def _set_instrument_combo_program(self, program: int | None) -> None:
        if program is None:
            self.midi_edit_instrument_combo.setCurrentIndex(0)
            return
        index = self.midi_edit_instrument_combo.findData(program)
        if index < 0:
            index = 0
        self.midi_edit_instrument_combo.setCurrentIndex(index)

    def _clip_note_events(self, clip: TimelineClip) -> list[dict[str, int]]:
        raw = self._timeline.midi_clip_data.get(clip.clip_id)
        if not isinstance(raw, dict):
            return []
        notes = raw.get("notes")
        if not isinstance(notes, list):
            return []
        output: list[dict[str, int]] = []
        for note in notes:
            if not isinstance(note, dict):
                continue
            try:
                start_tick = int(note.get("start_tick", 0))
                length_tick = int(note.get("length_tick", 0))
                pitch = int(note.get("pitch", 60))
                velocity = int(note.get("velocity", 90))
            except (TypeError, ValueError):
                continue
            output.append(
                {
                    "start_tick": max(start_tick, 0),
                    "length_tick": max(length_tick, 1),
                    "pitch": min(max(pitch, 0), 127),
                    "velocity": min(max(velocity, 1), 127),
                }
            )
        return output

    def _find_clip_at(self, track_id: str, bar: int) -> TimelineClip | None:
        for clip in self._timeline.clips_for_track(track_id):
            if clip.start_bar <= bar <= clip.end_bar:
                return clip
        return None

    def _find_clip_by_id(self, clip_id: str | None) -> TimelineClip | None:
        if not clip_id:
            return None
        return self._timeline.clips.get(clip_id)

    def _find_clip_for_selection(self, track_id: str, bar: int, clip_id: str | None = None) -> TimelineClip | None:
        selected = self._find_clip_by_id(clip_id)
        if selected is not None:
            return selected
        return self._find_clip_at(track_id, bar)

    def _clip_note_names(self, clip: TimelineClip) -> list[str]:
        result: set[int] = set()
        for note in self._clip_note_events(clip):
            result.add(note["pitch"])
        return [midi_note_name(pitch) for pitch in sorted(result)]

    def _ensure_editor_visible(self) -> None:
        if self._workspace_layout.get_rack_collapsed():
            self._apply_rack_collapsed_state(False)
        self.utility_tabs.setCurrentWidget(self.editor_tab)
        self.editor_scroll_area.ensureWidgetVisible(self.piano_roll_view)

    def open_editor_for_selection(self, track_id: str, bar: int, clip_id: str | None = None) -> None:
        self._selected_timeline_bar = min(max(int(bar), 1), self._timeline.bars)
        clip = self._find_clip_for_selection(track_id, self._selected_timeline_bar, clip_id)
        self.selected_clip_id = clip.clip_id if clip is not None else None
        self.track_input.setText(track_id)
        if hasattr(self, "compose_track_input"):
            self.compose_track_input.setText(track_id)
            self._refresh_compose_history()
        self._ensure_editor_visible()
        self._refresh_wav_info()
        self._refresh_history()
        self._refresh_timeline_view()
        self.editor_scroll_area.ensureWidgetVisible(self.piano_roll_view)

    def _update_pitch_display(self, track_id: str, bar: int, clip_id: str | None = None) -> None:
        clip = self._find_clip_for_selection(track_id, bar, clip_id)
        self.selected_clip_id = clip.clip_id if clip is not None else None
        raw = self._timeline.midi_clip_data.get(clip.clip_id, {}) if clip is not None else None
        if clip is None:
            self._clear_pitch_display()
            return
        if clip.clip_type != "midi":
            self._set_selected_clip_summary(clip, raw if isinstance(raw, dict) else None)
            self._clear_pitch_display(keep_clip_summary=True)
            return
        self._selected_midi_clip_id = clip.clip_id
        is_drum = bool(raw.get("is_drum")) if isinstance(raw, dict) else False
        self._set_selected_clip_summary(clip, raw if isinstance(raw, dict) else None)
        self._set_midi_edit_enabled(True, is_drum=is_drum)
        self.midi_transpose_spin.setValue(0)
        if isinstance(raw, dict):
            program_raw = raw.get("program")
            self._set_instrument_combo_program(program_raw if isinstance(program_raw, int) else None)

        note_events = self._clip_note_events(clip)
        ticks_per_beat = int(raw.get("ticks_per_beat", 960)) if isinstance(raw, dict) else 960
        bars = int(raw.get("bars", clip.length_bars)) if isinstance(raw, dict) else clip.length_bars
        total_ticks = max(1, bars) * max(1, ticks_per_beat) * 4
        if note_events:
            total_ticks = max(
                max(note["start_tick"] + note["length_tick"] for note in note_events),
                total_ticks,
            )
            self._updating_roll_from_model = True
            try:
                self.piano_roll_view.set_notes(
                    [
                        PianoRollNote(
                            start_tick=note["start_tick"],
                            length_tick=note["length_tick"],
                            pitch=note["pitch"],
                            velocity=note["velocity"],
                        )
                        for note in note_events
                    ],
                    total_ticks=total_ticks,
                )
            finally:
                self._updating_roll_from_model = False
            self.piano_roll_view.set_editable(True, self._on_piano_roll_notes_changed)
        else:
            self.piano_roll_view.set_notes([], total_ticks=total_ticks)
            self.piano_roll_view.set_editable(False, None)

        note_names = self._clip_note_names(clip)
        self.pitch_clip_label.setText(f"選択MIDIクリップ: {clip.name} ({clip.clip_id[:8]})")
        if not note_names:
            self.pitch_detail.setPlainText("音階: MIDIデータなし")
            return
        self.pitch_detail.setPlainText(
            "\n".join(
                [
                    f"音階数: {len(note_names)}",
                    "ノート: " + ", ".join(note_names),
                ]
            )
        )

    def _on_piano_roll_notes_changed(self, notes: list[PianoRollNote]) -> None:
        if self._updating_roll_from_model:
            return
        selected = self._selected_midi_clip()
        if selected is None:
            return
        clip, raw = selected
        notes_raw = raw.get("notes")
        if not isinstance(notes_raw, list):
            return
        if len(notes_raw) != len(notes):
            # Fallback: replace entirely when event count differs.
            channel = 9 if bool(raw.get("is_drum")) else 0
            raw["notes"] = [
                {
                    "start_tick": int(note.start_tick),
                    "length_tick": int(max(note.length_tick, 1)),
                    "pitch": int(min(max(note.pitch, 0), 127)),
                    "velocity": int(min(max(note.velocity, 1), 127)),
                    "channel": channel,
                }
                for note in notes
            ]
        else:
            for idx, note in enumerate(notes):
                item = notes_raw[idx]
                if not isinstance(item, dict):
                    item = {}
                    notes_raw[idx] = item
                item["start_tick"] = int(max(note.start_tick, 0))
                item["length_tick"] = int(max(note.length_tick, 1))
                item["pitch"] = int(min(max(note.pitch, 0), 127))
                item["velocity"] = int(min(max(note.velocity, 1), 127))
                if "channel" not in item:
                    item["channel"] = 9 if bool(raw.get("is_drum")) else 0

        self._timeline.midi_clip_data[clip.clip_id] = raw
        self._update_pitch_display(track_id=clip.track_id, bar=clip.start_bar, clip_id=clip.clip_id)
        self._refresh_timeline_view()
        self._set_status("ノートドラッグ編集を反映しました。")

    def _selected_midi_clip(self) -> tuple[TimelineClip, dict[str, object]] | None:
        clip_id = self._selected_midi_clip_id
        if clip_id is None:
            return None
        clip = self._timeline.clips.get(clip_id)
        if clip is None or clip.clip_type != "midi":
            return None
        raw = self._timeline.midi_clip_data.get(clip_id)
        if not isinstance(raw, dict):
            return None
        return clip, raw

    def _on_apply_midi_edit(self) -> None:
        selected = self._selected_midi_clip()
        if selected is None:
            self._show_error("先にDAWでMIDIクリップを選択してください。")
            return
        clip, raw = selected
        note_events = self._clip_note_events(clip)
        if not note_events:
            self._show_error("選択クリップに編集可能なMIDIノートがありません。")
            return

        transpose = int(self.midi_transpose_spin.value())
        if transpose != 0:
            for note in note_events:
                note["pitch"] = min(max(note["pitch"] + transpose, 0), 127)
        raw["notes"] = note_events
        is_drum = bool(raw.get("is_drum"))
        if not is_drum:
            program = self.midi_edit_instrument_combo.currentData()
            if isinstance(program, int):
                raw["program"] = int(program)
        self._timeline.midi_clip_data[clip.clip_id] = raw
        self.midi_transpose_spin.setValue(0)
        self._update_pitch_display(track_id=clip.track_id, bar=clip.start_bar, clip_id=clip.clip_id)
        self._set_status("MIDIクリップの音階/楽器変更を反映しました。")

    def _build_selected_midi_clip_draft(self) -> MidiClipDraft | None:
        selected = self._selected_midi_clip()
        if selected is None:
            return None
        clip, raw = selected
        notes_raw = self._clip_note_events(clip)
        if not notes_raw:
            return None

        events = [
            MidiNoteEvent(
                start_tick=note["start_tick"],
                length_tick=note["length_tick"],
                pitch=note["pitch"],
                velocity=note["velocity"],
                channel=9 if bool(raw.get("is_drum")) else 0,
            )
            for note in notes_raw
        ]
        grid_raw = raw.get("grid", "1/16")
        grid = grid_raw if isinstance(grid_raw, str) and grid_raw in SUPPORTED_GRIDS else "1/16"
        bars_raw = raw.get("bars")
        bars = int(bars_raw) if isinstance(bars_raw, int) and bars_raw > 0 else max(1, clip.length_bars)
        program_raw = raw.get("program")
        program = int(program_raw) if isinstance(program_raw, int) else None
        is_drum = bool(raw.get("is_drum"))
        if is_drum:
            program = None
        draft = MidiClipDraft(
            name=clip.name,
            bars=bars,
            grid=grid,  # type: ignore[arg-type]
            notes=events,
            program=program,
            is_drum=is_drum,
        )
        draft.validate()
        return draft

    def _on_preview_selected_midi(self) -> None:
        draft = self._build_selected_midi_clip_draft()
        if draft is None:
            self._show_error("先にDAWでMIDIクリップを選択してください。")
            return
        preview_path = self._preview_render_dir / f"timeline_midi_{self._selected_midi_clip_id}.wav"
        try:
            rendered = render_clip_to_wav(draft, preview_path)
        except Exception as exc:
            self._show_error(f"選択MIDIの試聴生成に失敗しました: {exc}")
            return
        if self._native_engine is None or not self._native_engine.is_available():
            self._set_status(f"選択MIDI試聴WAVを生成しました: {rendered.name}")
            return
        try:
            self._native_engine.stop_playback()
            self._stop_playback_sync()
            ok = self._native_engine.play_file(rendered)
        except Exception as exc:
            self._show_error(f"選択MIDIの試聴再生に失敗しました: {exc}")
            return
        if not ok:
            self._show_error("選択MIDIの試聴再生に失敗しました。")
            return
        track_id = self._current_track_id()
        self._start_playback_sync(track_id=track_id, duration_sec=_wav_duration_sec(rendered))
        self._set_status(f"選択MIDI試聴を開始しました: {rendered.name}")

    def _on_timeline_cell_clicked(self, row: int, column: int) -> None:
        tracks = self._timeline.tracks_in_order()
        if row < 0 or row >= len(tracks):
            return
        self._on_arranger_selection_requested(tracks[row].track_id, column + 1, "")

    def _on_transport_playhead_requested(self, bar: float) -> None:
        self._set_playhead_bar(bar, update_slider=False)

    def _prompt_arranger_instrument_choice(self) -> tuple[str, int | None, bool, str] | None:
        if QInputDialog is object:
            return ("ピアノ", 0, False, track_color_for_program(0))
        items = arranger_instrument_options()
        labels = [
            f"{label} ({'Drum' if is_drum else f'Program {program}'})"
            for label, program, is_drum in items
        ]
        selected_label, ok = QInputDialog.getItem(self, "新規トラックの楽器", "楽器", labels, 0, False)
        if not ok or not selected_label:
            return None
        index = labels.index(selected_label)
        instrument_name, program, is_drum = items[index]
        return (
            instrument_name,
            program,
            is_drum,
            track_color_for_program(program, is_drum=is_drum),
        )

    def create_track_from_instrument(
        self,
        instrument_name: str,
        program: int | None = None,
        *,
        is_drum: bool = False,
        color: str | None = None,
    ) -> TimelineTrack:
        track_number = len(self._timeline.tracks) + 1
        track = self._timeline.add_track(
            name=f"{instrument_name} {track_number}",
            instrument_name=instrument_name,
            program=program,
            is_drum=is_drum,
            color=color or track_color_for_program(program, is_drum=is_drum),
        )
        return track

    def create_clip_from_arranger_drag(
        self,
        track_id: str | None,
        start_bar: int,
        end_bar: int,
        lane_index: int,
    ) -> TimelineClip | None:
        start = min(max(int(start_bar), 1), self._timeline.max_bars)
        end = min(max(int(end_bar), start), self._timeline.max_bars)
        target_track_id = track_id or ""
        tracks = self._timeline.tracks_in_order()
        if not target_track_id and 0 <= lane_index < len(tracks):
            target_track_id = tracks[lane_index].track_id

        if target_track_id in self._timeline.tracks:
            track = self._timeline.tracks[target_track_id]
        else:
            self.pending_track_creation_from_pencil = (start, end, lane_index)
            choice = self._prompt_arranger_instrument_choice()
            self.pending_track_creation_from_pencil = None
            if choice is None:
                return None
            instrument_name, program, is_drum, color = choice
            track = self.create_track_from_instrument(
                instrument_name,
                program,
                is_drum=is_drum,
                color=color,
            )
            target_track_id = track.track_id

        track_clips = self._timeline.clips_for_track(target_track_id)
        clip_name = f"{track.instrument_name} Clip {len(track_clips) + 1}"
        midi_data = {
            "name": clip_name,
            "bars": end - start + 1,
            "grid": "1/16",
            "notes": [],
            "program": None if track.is_drum else track.program,
            "is_drum": track.is_drum,
            "ticks_per_beat": 960,
        }
        clip = self._timeline.add_clip(
            target_track_id,
            "midi",
            start_bar=start,
            length_bars=end - start + 1,
            name=clip_name,
            midi_data=midi_data,
        )
        self.open_editor_for_selection(target_track_id, clip.start_bar, clip.clip_id)
        self._set_status(f"アレンジャーにMIDIクリップを追加しました: {clip.name}")
        return clip

    def _on_arranger_selection_requested(self, track_id: str, bar: int, clip_id: str = "") -> None:
        self.open_editor_for_selection(track_id, bar, clip_id or None)
        self._set_status(f"選択トラックを {track_id} に変更しました。")

    def _on_arranger_clip_creation_requested(self, track_id: str, start_bar: int, end_bar: int, lane_index: int) -> None:
        clip = self.create_clip_from_arranger_drag(track_id or None, start_bar, end_bar, lane_index)
        if clip is None:
            self._set_status("クリップ作成をキャンセルしました。")

    def _on_add_track(self) -> None:
        track = self.create_track_from_instrument("ピアノ", 0)
        self.open_editor_for_selection(track.track_id, 1)
        self._set_status(f"トラックを追加しました: {track.track_id}")

    def _on_add_clip(self, clip_type: str) -> None:
        track_id = self._current_track_id()
        if track_id not in self._timeline.tracks:
            self._show_error(f"トラックID '{track_id}' はタイムラインに存在しません。")
            return
        track = self._timeline.tracks[track_id]
        track_clips = self._timeline.clips_for_track(track_id)
        start_bar = 1 if not track_clips else track_clips[-1].end_bar + 1
        length = 4 if clip_type == "midi" else 8
        if start_bar + length - 1 > self._timeline.max_bars:
            self._show_error("1000小節を超えるため、これ以上クリップを配置できません。")
            return
        name = f"{'MIDI' if clip_type == 'midi' else 'Audio'} Clip {len(track_clips) + 1}"
        midi_data = None
        if clip_type == "midi":
            midi_data = {
                "name": name,
                "bars": length,
                "grid": "1/16",
                "notes": [],
                "program": None if track.is_drum else track.program,
                "is_drum": track.is_drum,
                "ticks_per_beat": 960,
            }
        clip = self._timeline.add_clip(
            track_id,
            clip_type,
            start_bar=start_bar,
            length_bars=length,
            name=name,
            midi_data=midi_data,
        )
        self.open_editor_for_selection(track_id, start_bar, clip.clip_id)
        self._set_status(f"{clip_type.upper()} クリップを追加しました。")

    def _on_load_wav(self) -> None:
        track_id = self._current_track_id()
        if track_id not in self._timeline.tracks:
            self._show_error(f"トラックID '{track_id}' はタイムラインに存在しません。")
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "WAVファイルを選択", "", "WAV Files (*.wav)")
        if not file_path:
            return
        self._stop_playback_sync()
        if self._native_engine is not None and self._native_engine.is_available():
            self._native_engine.stop_playback()
        try:
            info = self._waveforms.load_track_wav(track_id, file_path)
        except Exception as exc:
            self._show_error(f"WAV読込に失敗しました: {exc}")
            return

        self._clear_preview_render(track_id)
        clip = self._add_audio_clip_from_wave(track_id, Path(file_path).stem, info.duration_sec)
        self.open_editor_for_selection(track_id, clip.start_bar, clip.clip_id)
        self._set_status(
            f"WAVを読込しました: {Path(file_path).name} "
            f"({info.sample_rate}Hz, {info.duration_sec:.2f}s)"
        )

    def _add_audio_clip_from_wave(self, track_id: str, name: str, duration_sec: float) -> TimelineClip:
        bars = max(1, math.ceil(duration_sec / self._seconds_per_bar()))
        track_clips = self._timeline.clips_for_track(track_id)
        start_bar = 1 if not track_clips else track_clips[-1].end_bar + 1
        if start_bar + bars - 1 > self._timeline.max_bars:
            bars = max(1, self._timeline.max_bars - start_bar + 1)
        return self._timeline.add_clip(track_id, "audio", start_bar=start_bar, length_bars=bars, name=name)

    def _on_play_wav(self) -> None:
        track_id = self._current_track_id()
        item = self._waveforms.get_item(track_id)
        if item is None:
            self._show_error("このトラックにはWAVが読込されていません。")
            return
        if self._native_engine is None or not self._native_engine.is_available():
            self._show_error("ネイティブ音声エンジンを利用できません。")
            return
        try:
            playback_path, is_rendered = self._resolve_playback_wav(track_id, item.path)
        except Exception as exc:
            self._show_error(f"再生用WAVの準備に失敗しました: {exc}")
            return

        ok = self._native_engine.play_file(playback_path)
        if not ok:
            self._show_error("WAV再生に失敗しました。")
            return
        self._start_playback_sync(track_id=track_id, duration_sec=item.duration_sec)
        source_label = "提案反映音" if is_rendered else "元WAV"
        self._set_status(f"再生開始: {item.path.name} ({source_label}, {self._native_engine.backend_name()})")

    def _on_stop_wav(self) -> None:
        if self._native_engine is None or not self._native_engine.is_available():
            self._show_error("ネイティブ音声エンジンを利用できません。")
            return
        self._native_engine.stop_playback()
        self._stop_playback_sync()
        self._refresh_waveform_playhead()
        self._set_status("再生を停止しました。")

    def _start_playback_sync(self, track_id: str, duration_sec: float) -> None:
        self._playback_track_id = track_id
        self._playback_started_at = time.perf_counter()
        self._playback_duration_sec = max(duration_sec, 0.01)
        self._playback_elapsed_sec = 0.0
        self._set_playhead_bar(1.0)
        if self._playback_timer is not None:
            self._playback_timer.start()
        self._refresh_shell_state()

    def _stop_playback_sync(self) -> None:
        self._playback_track_id = None
        self._playback_started_at = None
        self._playback_duration_sec = 0.0
        self._playback_elapsed_sec = 0.0
        if self._playback_timer is not None:
            self._playback_timer.stop()
        self._refresh_shell_state()

    def _on_playback_tick(self) -> None:
        if self._playback_started_at is None:
            return
        elapsed = time.perf_counter() - self._playback_started_at
        self._playback_elapsed_sec = elapsed
        if elapsed >= self._playback_duration_sec:
            self._playback_elapsed_sec = self._playback_duration_sec
            end_bar = self._seconds_to_bar(self._playback_duration_sec)
            self._set_playhead_bar(end_bar)
            if self._current_track_id() == self._playback_track_id:
                self.waveform_view.set_playhead_ratio(1.0)
            self._stop_playback_sync()
            self._set_status("再生終了")
            return
        self._set_playhead_bar(self._seconds_to_bar(elapsed))

    def _resolve_playback_wav(self, track_id: str, original_path: Path) -> tuple[Path, bool]:
        track_state = self._mixing.get_track_state(track_id)
        if not is_track_processing_active(track_state):
            return original_path, False

        rendered_path = self._preview_render_path(track_id)
        render_track_preview_wav(original_path, rendered_path, track_state)
        return rendered_path, True

    def _preview_render_path(self, track_id: str) -> Path:
        safe_track_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in track_id).strip("_")
        if not safe_track_id:
            safe_track_id = "track"
        return self._preview_render_dir / f"{safe_track_id}.wav"

    def _clear_preview_render(self, track_id: str) -> None:
        rendered_path = self._preview_render_path(track_id)
        try:
            rendered_path.unlink(missing_ok=True)
        except OSError:
            # If cleanup fails, keep going; next render will overwrite.
            pass

    def _refresh_wav_info(self) -> None:
        track_id = self._current_track_id()
        item = self._waveforms.get_item(track_id)
        if item is None:
            self.wav_info_label.setText("WAV未読込")
            self.waveform_view.clear()
            self._refresh_shell_state()
            return
        self.wav_info_label.setText(f"{item.path.name} | {item.sample_rate}Hz | {item.duration_sec:.2f}s")
        self._refresh_waveform_view()

    def _on_dry_wet_changed(self, value: int) -> None:
        self.dry_wet_label.setText(f"{value}%")
        self._refresh_shell_state()

    def _current_track_id(self) -> str:
        track_id = self.track_input.text().strip()
        return track_id if track_id else "track-1"

    def _current_mode(self) -> str:
        current = self.mode_combo.currentData()
        return current if isinstance(current, str) else "quick"

    def _current_profile(self) -> str:
        current = self.profile_combo.currentData()
        return current if isinstance(current, str) else "clean"

    def _current_suggestion_engine(self) -> str:
        current = self.suggestion_engine_combo.currentData()
        return current if isinstance(current, str) else "rule-based"

    def _current_compose_track_id(self) -> str:
        if hasattr(self, "compose_track_input"):
            track_id = self.compose_track_input.text().strip()
            if track_id:
                return track_id
        return self._current_track_id()

    def _current_compose_part(self) -> str:
        current = self.compose_part_combo.currentData()
        return current if isinstance(current, str) else "chord"

    def _current_compose_key(self) -> str:
        current = self.compose_key_combo.currentData()
        return current if isinstance(current, str) else "C"

    def _current_compose_scale(self) -> str:
        current = self.compose_scale_combo.currentData()
        return current if isinstance(current, str) else "major"

    def _current_compose_style(self) -> str:
        current = self.compose_style_combo.currentData()
        return current if isinstance(current, str) else "pop"

    def _current_compose_grid(self) -> str:
        current = self.compose_grid_combo.currentData()
        return current if isinstance(current, str) else "1/16"

    def _current_compose_engine(self) -> str:
        current = self.compose_engine_combo.currentData()
        return current if isinstance(current, str) else "rule-based"

    def _current_compose_program(self) -> int | None:
        if self._current_compose_part() == "drum":
            return None
        current = self.compose_instrument_combo.currentData()
        return int(current) if isinstance(current, int) else 0

    def _on_compose_part_changed(self, _index: int | None = None) -> None:
        is_drum = self._current_compose_part() == "drum"
        self.compose_instrument_combo.setEnabled(not is_drum)
        self._refresh_shell_state()

    def _sync_phrase_range_with_bars(self, _value: int | None = None) -> None:
        bars = int(self.compose_bars_spin.value())
        self.compose_phrase_from_spin.setMaximum(bars)
        self.compose_phrase_to_spin.setMaximum(bars)
        if self.compose_phrase_from_spin.value() > bars:
            self.compose_phrase_from_spin.setValue(bars)
        if self.compose_phrase_to_spin.value() > bars:
            self.compose_phrase_to_spin.setValue(bars)
        self._normalize_phrase_range()

    def _normalize_phrase_range(self, _value: int | None = None) -> None:
        start = int(self.compose_phrase_from_spin.value())
        end = int(self.compose_phrase_to_spin.value())
        if start > end:
            self.compose_phrase_to_spin.blockSignals(True)
            self.compose_phrase_to_spin.setValue(start)
            self.compose_phrase_to_spin.blockSignals(False)

    def _phrase_range(self) -> tuple[int, int]:
        start = int(self.compose_phrase_from_spin.value())
        end = int(self.compose_phrase_to_spin.value())
        if start > end:
            start, end = end, start
        return start, end

    def _selected_compose_suggestion_id(self) -> str | None:
        item = self.compose_suggestion_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, str) else None

    def _refresh_compose_ab_label(self) -> None:
        a = self._compose_ab_slots["A"]
        b = self._compose_ab_slots["B"]
        self.compose_ab_label.setText(
            f"A: {(a[:8] if isinstance(a, str) else '未設定')} / "
            f"B: {(b[:8] if isinstance(b, str) else '未設定')}"
        )

    def _set_compose_ab(self, slot: str) -> None:
        suggestion_id = self._selected_compose_suggestion_id()
        if suggestion_id is None:
            self._show_error("先に作曲提案を1つ選択してください。")
            return
        self._compose_ab_slots[slot] = suggestion_id
        self._refresh_compose_ab_label()
        self._set_status(f"{slot}に提案 {suggestion_id[:8]} を設定しました。")

    def _on_set_compose_ab_a(self) -> None:
        self._set_compose_ab("A")

    def _on_set_compose_ab_b(self) -> None:
        self._set_compose_ab("B")

    def _preview_compose_suggestion_by_id(self, suggestion_id: str) -> None:
        try:
            preview_wav = self._composition.preview(suggestion_id=suggestion_id)
        except Exception as exc:
            self._show_error(f"作曲試聴WAV生成に失敗しました: {exc}")
            return
        if self._native_engine is None or not self._native_engine.is_available():
            self._set_status(f"作曲試聴WAVを生成しました: {preview_wav}")
            return
        try:
            self._native_engine.stop_playback()
            self._stop_playback_sync()
            ok = self._native_engine.play_file(preview_wav)
        except Exception as exc:
            self._show_error(f"作曲試聴の再生に失敗しました: {exc}")
            return
        if not ok:
            self._show_error("作曲試聴の再生に失敗しました。")
            return
        track_id = self._current_compose_track_id()
        self.track_input.setText(track_id)
        self._start_playback_sync(track_id=track_id, duration_sec=_wav_duration_sec(preview_wav))
        self._set_status(f"作曲試聴を開始しました: {preview_wav.name}")

    def _on_compose_preview_a(self) -> None:
        suggestion_id = self._compose_ab_slots["A"]
        if not isinstance(suggestion_id, str):
            self._show_error("Aが未設定です。")
            return
        self._preview_compose_suggestion_by_id(suggestion_id)

    def _on_compose_preview_b(self) -> None:
        suggestion_id = self._compose_ab_slots["B"]
        if not isinstance(suggestion_id, str):
            self._show_error("Bが未設定です。")
            return
        self._preview_compose_suggestion_by_id(suggestion_id)

    def _on_compose_compare_ab(self) -> None:
        a_id = self._compose_ab_slots["A"]
        b_id = self._compose_ab_slots["B"]
        if not isinstance(a_id, str) or not isinstance(b_id, str):
            self._show_error("A/Bの両方を設定してください。")
            return
        a = self._compose_suggestions.get(a_id)
        b = self._compose_suggestions.get(b_id)
        if a is None or b is None:
            self._show_error("A/B比較対象が現在の候補に存在しません。再提案してください。")
            return
        self.compose_compare_detail.setPlainText(_compose_ab_compare_text(a, b))
        self.utility_tabs.setCurrentWidget(self.compose_compare_tab)
        self._set_status("A/B比較を更新しました。")

    def _selected_compose_command_id(self) -> str | None:
        item = self.compose_history_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, str) else None

    def _on_compose_suggest(self) -> None:
        track_id = self._current_compose_track_id()
        self.track_input.setText(track_id)
        request = ComposeRequest(
            track_id=track_id,
            part=self._current_compose_part(),  # type: ignore[arg-type]
            key=self._current_compose_key(),  # type: ignore[arg-type]
            scale=self._current_compose_scale(),  # type: ignore[arg-type]
            bars=int(self.compose_bars_spin.value()),
            style=self._current_compose_style(),  # type: ignore[arg-type]
            grid=self._current_compose_grid(),  # type: ignore[arg-type]
            program=self._current_compose_program(),
        )
        engine = self._current_compose_engine()
        self._composition.set_engine(engine)  # type: ignore[arg-type]
        try:
            suggestions = self._composition.suggest(request=request, engine_mode=engine)  # type: ignore[arg-type]
        except Exception as exc:
            self._show_error(f"作曲提案の生成に失敗しました: {exc}")
            return

        self._compose_suggestions = {item.suggestion_id: item for item in suggestions}
        self._compose_ab_slots = {"A": None, "B": None}
        self._refresh_compose_ab_label()
        self.compose_suggestion_list.clear()
        self.compose_detail.clear()
        self.compose_compare_detail.clear()
        for index, suggestion in enumerate(suggestions, start=1):
            note_count = len(suggestion.clips[0].notes) if suggestion.clips else 0
            line = (
                f"{index}. {_compose_source_label(suggestion.source)} | "
                f"スコア={suggestion.score:.3f} | ノート={note_count} | {suggestion.suggestion_id[:8]}"
            )
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, suggestion.suggestion_id)
            self.compose_suggestion_list.addItem(item)
        if self.compose_suggestion_list.count() > 0:
            self.compose_suggestion_list.setCurrentRow(0)
        if self.compose_suggestion_list.count() > 1:
            a_item = self.compose_suggestion_list.item(0)
            b_item = self.compose_suggestion_list.item(1)
            a_id = a_item.data(Qt.ItemDataRole.UserRole) if a_item is not None else None
            b_id = b_item.data(Qt.ItemDataRole.UserRole) if b_item is not None else None
            self._compose_ab_slots["A"] = a_id if isinstance(a_id, str) else None
            self._compose_ab_slots["B"] = b_id if isinstance(b_id, str) else None
            self._refresh_compose_ab_label()

        source = self._composition.get_last_source()
        fallback = self._composition.get_last_fallback_reason()
        self.utility_tabs.setCurrentIndex(2)
        if fallback:
            self._set_status(f"作曲提案{len(suggestions)}件: {_compose_source_label(source)} / 理由: {fallback}")
        else:
            self._set_status(f"作曲提案{len(suggestions)}件を生成しました（{_compose_source_label(source)}）。")

    def _on_compose_suggestion_selected(
        self,
        current: QListWidgetItem | None,
        _prev: QListWidgetItem | None,
    ) -> None:
        if current is None:
            self.compose_detail.clear()
            return
        suggestion_id = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(suggestion_id, str):
            self.compose_detail.clear()
            return
        suggestion = self._compose_suggestions.get(suggestion_id)
        if suggestion is None:
            self.compose_detail.clear()
            return

        clip = suggestion.clips[0] if suggestion.clips else None
        bars = suggestion.request.bars
        self.compose_phrase_from_spin.setMaximum(bars)
        self.compose_phrase_to_spin.setMaximum(bars)
        if self.compose_phrase_from_spin.value() > bars:
            self.compose_phrase_from_spin.setValue(bars)
        if self.compose_phrase_to_spin.value() > bars:
            self.compose_phrase_to_spin.setValue(bars)
        self._normalize_phrase_range()
        note_count = len(clip.notes) if clip else 0
        lines = [
            f"提案ID: {suggestion.suggestion_id}",
            f"パート: {_compose_part_label(suggestion.request.part)}",
            f"キー: {suggestion.request.key}",
            f"スケール: {'メジャー' if suggestion.request.scale == 'major' else 'マイナー'}",
            f"スタイル: {suggestion.request.style}",
            f"グリッド: {suggestion.request.grid}",
            f"小節数: {suggestion.request.bars}",
            f"楽器Program: {suggestion.request.program if suggestion.request.program is not None else 'ドラム'}",
            f"ソース: {_compose_source_label(suggestion.source)}",
            f"スコア: {suggestion.score:.4f}",
            f"理由: {suggestion.reason}",
            f"ノート数: {note_count}",
        ]
        if clip is not None:
            lines.append(f"クリップ名: {clip.name}")
        self.compose_detail.setPlainText("\n".join(lines))

    def _on_compose_preview(self) -> None:
        suggestion_id = self._selected_compose_suggestion_id()
        if suggestion_id is None:
            self._show_error("先に作曲提案を1つ選択してください。")
            return
        self._preview_compose_suggestion_by_id(suggestion_id)

    def _on_compose_apply(self) -> None:
        suggestion_id = self._selected_compose_suggestion_id()
        if suggestion_id is None:
            self._show_error("先に作曲提案を1つ選択してください。")
            return
        phrase_start, phrase_end = self._phrase_range()
        try:
            command_id, clip_ids = self._composition.apply_to_timeline(
                suggestion_id=suggestion_id,
                phrase_start_bar=phrase_start,
                phrase_end_bar=phrase_end,
            )
        except Exception as exc:
            self._show_error(f"タイムライン挿入に失敗しました: {exc}")
            return
        self._refresh_timeline_view()
        self._sync_track_controls_from_timeline()
        self._refresh_compose_history()
        if clip_ids:
            first_clip_id = clip_ids[0]
            inserted = self._timeline.clips.get(first_clip_id)
            if inserted is not None:
                self.open_editor_for_selection(inserted.track_id, inserted.start_bar, first_clip_id)
                self.inspector_tabs.setCurrentIndex(0)
        self._set_status(
            f"作曲クリップを{len(clip_ids)}件挿入しました（bar {phrase_start}-{phrase_end}）。"
            f"コマンドID={command_id}"
        )

    def _on_compose_revert(self) -> None:
        command_id = self._selected_compose_command_id()
        if command_id is None:
            self._show_error("先に作曲履歴からコマンドを1つ選択してください。")
            return
        try:
            self._composition.revert(command_id=command_id)
        except Exception as exc:
            self._show_error(f"作曲挿入の巻き戻しに失敗しました: {exc}")
            return
        self._refresh_timeline_view()
        self._refresh_compose_history()
        self.utility_tabs.setCurrentWidget(self.compose_history_tab)
        self._set_status(f"作曲挿入を巻き戻しました。コマンドID={command_id}")

    def _refresh_compose_history(self) -> None:
        history = self._composition.get_history(track_id=self._current_compose_track_id())
        self.compose_history_list.clear()
        self.compose_history_detail.clear()
        for command in history:
            item = QListWidgetItem(_format_compose_history_line(command))
            item.setData(Qt.ItemDataRole.UserRole, command.command_id)
            self.compose_history_list.addItem(item)
        if self.compose_history_list.count() > 0:
            self.compose_history_list.setCurrentRow(0)

    def _on_compose_history_selected(
        self,
        current: QListWidgetItem | None,
        _prev: QListWidgetItem | None,
    ) -> None:
        if current is None:
            self.compose_history_detail.clear()
            return
        command_id = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(command_id, str):
            self.compose_history_detail.clear()
            return
        history = self._composition.get_history(track_id=self._current_compose_track_id())
        selected = next((item for item in history if item.command_id == command_id), None)
        if selected is None:
            self.compose_history_detail.clear()
            return
        self.compose_history_detail.setPlainText(
            "\n".join(
                [
                    f"コマンドID: {selected.command_id}",
                    f"トラックID: {selected.track_id}",
                    f"提案ID: {selected.suggestion_id}",
                    f"作成時刻: {selected.created_at.isoformat()}",
                    f"状態: {'適用中' if selected.applied else '巻き戻し済み'}",
                    f"作成クリップID: {', '.join(selected.created_clip_ids)}",
                ]
            )
        )

    def _on_suggestion_engine_changed(self, _index: int | None = None) -> None:
        engine = self._current_suggestion_engine()
        self._mixing.set_suggestion_mode(engine)
        label = "LLMベース" if engine == "llm-based" else "ルールベース"
        self._set_status(f"提案エンジンを {label} に変更しました。")

    def _on_analyze(self) -> None:
        track_id = self._current_track_id()
        mode = self._current_mode()
        try:
            analysis_id = self._mixing.analyze([track_id], mode=mode)
            snapshot = self._mixing.get_snapshot(analysis_id)
            features = snapshot.track_features[track_id]
        except Exception as exc:
            self._show_error(str(exc))
            return

        self._latest_analysis_id = analysis_id
        self.analysis_summary.setPlainText(
            "\n".join(
                [
                    f"解析ID: {analysis_id}",
                    f"モード: {snapshot.mode.value}",
                    f"トラック: {track_id}",
                    f"LUFS: {features.lufs:.2f}",
                    f"ピーク(dBFS): {features.peak_dbfs:.2f}",
                    f"RMS(dBFS): {features.rms_dbfs:.2f}",
                    f"クレストファクター(dB): {features.crest_factor_db:.2f}",
                    f"スペクトル重心(Hz): {features.spectral_centroid_hz:.2f}",
                    f"ダイナミックレンジ(dB): {features.dynamic_range_db:.2f}",
                    f"ラウドネスレンジ(dB): {features.loudness_range_db:.2f}",
                    f"トランジェント密度: {features.transient_density:.4f}",
                    f"ゼロクロス率: {features.zero_crossing_rate:.4f}",
                ]
            )
        )
        self._set_status(f"解析完了: {analysis_id}")

    def _on_suggest(self) -> None:
        track_id = self._current_track_id()
        profile = self._current_profile()
        mode = self._current_mode()
        engine = self._current_suggestion_engine()
        try:
            suggestions = self._mixing.suggest(
                track_id=track_id,
                profile=profile,
                analysis_id=self._latest_analysis_id,
                mode=mode,
                engine_mode=engine,
            )
        except Exception as exc:
            self._show_error(str(exc))
            return

        self._suggestions = {item.suggestion_id: item for item in suggestions}
        self.suggestion_list.clear()
        self.suggestion_detail.clear()
        for index, suggestion in enumerate(suggestions, start=1):
            line = (
                f"{index}. {_variant_label(suggestion.variant)} | "
                f"スコア={suggestion.score:.3f} | {suggestion.suggestion_id[:8]}"
            )
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, suggestion.suggestion_id)
            self.suggestion_list.addItem(item)
        if self.suggestion_list.count() > 0:
            self.suggestion_list.setCurrentRow(0)
        source = self._mixing.get_last_suggestion_source()
        fallback = self._mixing.get_last_suggestion_fallback_reason()
        source_label = {
            "rule-based": "ルールベース",
            "llm-based": "LLMベース",
            "rule-based-fallback": "ルールベース（LLMフォールバック）",
        }.get(source, source)
        if fallback:
            self._set_status(f"{len(suggestions)}件生成: {source_label} / 理由: {fallback}")
        else:
            self._set_status(f"{len(suggestions)}件の提案候補を生成しました（{source_label}）。")
        self.utility_tabs.setCurrentIndex(0)

    def _on_suggestion_selected(self, current: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if current is None:
            self.suggestion_detail.clear()
            return
        suggestion_id = current.data(Qt.ItemDataRole.UserRole)
        suggestion = self._suggestions.get(suggestion_id)
        if suggestion is None:
            self.suggestion_detail.clear()
            return
        lines = [
            f"提案ID: {suggestion.suggestion_id}",
            f"プロファイル: {suggestion.profile}",
            f"バリエーション: {_variant_label(suggestion.variant)}",
            f"スコア: {suggestion.score:.4f}",
            f"理由: {suggestion.reason}",
            "パラメータ更新:",
        ]
        for effect_type, params in suggestion.param_updates.items():
            lines.append(f"  - {effect_type.value}")
            for key, value in params.items():
                lines.append(f"      {key}: {value:.4f}")
        self.suggestion_detail.setPlainText("\n".join(lines))

    def _selected_suggestion_id(self) -> str | None:
        item = self.suggestion_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_preview(self) -> None:
        track_id = self._current_track_id()
        suggestion_id = self._selected_suggestion_id()
        if not suggestion_id:
            self._show_error("先に提案を1つ選択してください。")
            return
        dry_wet = self.dry_wet_slider.value() / 100.0
        try:
            self._mixing.preview(track_id=track_id, suggestion_id=suggestion_id, dry_wet=dry_wet)
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._set_status(f"試聴を反映しました（Dry/Wet={dry_wet:.2f}）")

    def _on_cancel_preview(self) -> None:
        track_id = self._current_track_id()
        self._mixing.cancel_preview(track_id)
        self._set_status("試聴を取り消しました。")

    def _on_apply(self) -> None:
        track_id = self._current_track_id()
        suggestion_id = self._selected_suggestion_id()
        if not suggestion_id:
            self._show_error("先に提案を1つ選択してください。")
            return
        try:
            command_id = self._mixing.apply(track_id=track_id, suggestion_id=suggestion_id)
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._refresh_history()
        self.utility_tabs.setCurrentIndex(1)
        self._set_status(f"提案を適用しました。コマンドID={command_id}")

    def _on_revert(self) -> None:
        selected = self.history_list.currentItem()
        if selected is None:
            self._show_error("先に履歴からコマンドを1つ選択してください。")
            return
        command_id = selected.data(Qt.ItemDataRole.UserRole)
        try:
            self._mixing.revert(command_id)
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._refresh_history()
        self.utility_tabs.setCurrentIndex(1)
        self._set_status(f"巻き戻ししました。コマンドID={command_id}")

    def _refresh_history(self) -> None:
        track_id = self._current_track_id()
        history = self._mixing.get_command_history(track_id=track_id)
        self.history_list.clear()
        self.history_detail.clear()
        for command in history:
            item = QListWidgetItem(_format_history_line(command))
            item.setData(Qt.ItemDataRole.UserRole, command.command_id)
            self.history_list.addItem(item)
        if self.history_list.count() > 0:
            self.history_list.setCurrentRow(0)

    def _on_history_selected(self, current: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if current is None:
            self.history_detail.clear()
            return
        command_id = current.data(Qt.ItemDataRole.UserRole)
        history = self._mixing.get_command_history(track_id=self._current_track_id())
        selected = next((item for item in history if item.command_id == command_id), None)
        if selected is None:
            self.history_detail.clear()
            return
        self.history_detail.setPlainText(
            "\n".join(
                [
                    f"コマンドID: {selected.command_id}",
                    f"トラックID: {selected.track_id}",
                    f"提案ID: {selected.suggestion_id}",
                    f"作成時刻: {selected.created_at.isoformat()}",
                    f"状態: {'適用中' if selected.applied else '巻き戻し済み'}",
                ]
            )
        )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._stop_playback_sync()
        if self._native_engine is not None and self._native_engine.is_available():
            self._native_engine.stop_playback()
            self._native_engine.stop()
        super().closeEvent(event)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "エラー", message)
        self._set_status(f"エラー: {message}")

    def _set_status(self, message: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.status_label.setText(f"[{now}] {message}")
        self._refresh_shell_state()


def _format_history_line(command: SuggestionCommand) -> str:
    stamp = command.created_at.strftime("%H:%M:%S")
    state = "適用中" if command.applied else "巻き戻し済み"
    return f"{stamp} | {command.command_id[:8]} | {state} | {command.suggestion_id[:8]}"


def _variant_label(variant: str) -> str:
    return {
        "balanced": "バランス",
        "tight": "タイト",
        "wide": "ワイド",
    }.get(variant, variant)


def _compose_source_label(source: str) -> str:
    return {
        "rule-based": "ルールベース",
        "llm-based": "LLMベース",
        "rule-based-fallback": "ルールベース（LLMフォールバック）",
    }.get(source, source)


def _compose_part_label(part: str) -> str:
    return {
        "chord": "コード",
        "melody": "メロディ",
        "drum": "ドラム",
    }.get(part, part)


def _format_compose_history_line(command: ComposeCommand) -> str:
    stamp = command.created_at.strftime("%H:%M:%S")
    state = "適用中" if command.applied else "巻き戻し済み"
    return f"{stamp} | {command.command_id[:8]} | {state} | {command.suggestion_id[:8]}"


def _compose_ab_compare_text(a: ComposeSuggestion, b: ComposeSuggestion) -> str:
    a_clip = a.clips[0] if a.clips else None
    b_clip = b.clips[0] if b.clips else None
    a_notes = len(a_clip.notes) if a_clip else 0
    b_notes = len(b_clip.notes) if b_clip else 0
    a_program = a.request.program if a.request.program is not None else "drum"
    b_program = b.request.program if b.request.program is not None else "drum"
    return "\n".join(
        [
            "A/B比較",
            f"A: {a.suggestion_id[:8]} | score={a.score:.4f} | notes={a_notes} | bars={a.request.bars} | program={a_program} | source={a.source}",
            f"B: {b.suggestion_id[:8]} | score={b.score:.4f} | notes={b_notes} | bars={b.request.bars} | program={b_program} | source={b.source}",
            f"score差 (A-B): {a.score - b.score:+.4f}",
            f"note差 (A-B): {a_notes - b_notes:+d}",
            f"A理由: {a.reason}",
            f"B理由: {b.reason}",
        ]
    )


def _wav_duration_sec(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            frame_rate = wav.getframerate()
            if frame_rate <= 0:
                return 0.01
            return max(frames / frame_rate, 0.01)
    except Exception:
        return 0.01


def main() -> int:
    if QApplication is None:  # pragma: no cover - runtime-only path
        print("PySide6 がインストールされていません。`pip install -e .[ui]` を実行してください。")
        return 1
    app = QApplication(sys.argv)
    window = IntegratedWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
