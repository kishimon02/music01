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
from music_create.ui.timeline import TimelineClip, TimelineState
from music_create.ui.waveform import WaveformView

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QComboBox,
        QFileDialog,
        QFrame,
        QFormLayout,
        QGroupBox,
        QHeaderView,
        QHBoxLayout,
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
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover - runtime-only path
    QTimer = object  # type: ignore[assignment]
    QAbstractItemView = object  # type: ignore[assignment]
    QApplication = None  # type: ignore[assignment]
    QFileDialog = object  # type: ignore[assignment]
    QComboBox = object  # type: ignore[assignment]
    QFrame = object  # type: ignore[assignment]
    QFormLayout = object  # type: ignore[assignment]
    QGroupBox = object  # type: ignore[assignment]
    QHeaderView = object  # type: ignore[assignment]
    QHBoxLayout = object  # type: ignore[assignment]
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
    QSplitter = object  # type: ignore[assignment]
    QTabWidget = object  # type: ignore[assignment]
    QTableWidget = object  # type: ignore[assignment]
    QTableWidgetItem = object  # type: ignore[assignment]
    QTextEdit = object  # type: ignore[assignment]
    QVBoxLayout = object  # type: ignore[assignment]
    QWidget = object  # type: ignore[assignment]
    QColor = object  # type: ignore[assignment]
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


def midi_note_name(pitch: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    normalized = min(max(int(pitch), 0), 127)
    octave = (normalized // 12) - 1
    return f"{names[normalized % 12]}{octave}"


def pitch_class_guide_text() -> str:
    return "C C# D D# E F F# G G# A A# B"


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
        self._selected_midi_clip_id: str | None = None
        self._selected_timeline_bar = 1
        self._updating_roll_from_model = False
        self._timeline = TimelineState(bars=16)
        self._composition = Composition(service=CompositionService(self._timeline))
        self._init_default_timeline()
        self._preview_render_dir = Path(tempfile.gettempdir()) / "music_create" / "preview_wav"
        self._preview_render_dir.mkdir(parents=True, exist_ok=True)
        self._tempo_bpm = 120.0
        self._beats_per_bar = 4.0
        self._playback_track_id: str | None = None
        self._playback_started_at: float | None = None
        self._playback_duration_sec = 0.0
        self._playback_elapsed_sec = 0.0
        self._playback_timer: QTimer | None = None
        if QTimer is not object:
            self._playback_timer = QTimer(self)
            self._playback_timer.setInterval(33)
            self._playback_timer.timeout.connect(self._on_playback_tick)

        self._build_ui()
        self._sync_track_controls_from_timeline()
        self._refresh_timeline_view()
        self._refresh_wav_info()

    def _init_default_timeline(self) -> None:
        track1 = self._timeline.add_track("Track 1")
        track2 = self._timeline.add_track("Track 2")
        self._timeline.add_clip(track1.track_id, "midi", start_bar=1, length_bars=4, name="Intro Chords")
        self._timeline.add_clip(track1.track_id, "midi", start_bar=5, length_bars=4, name="Lead Hook")
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
        scroll.setWidget(content)
        return scroll

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
        self.workspace_splitter.addWidget(self._build_utility_rack())
        self.workspace_splitter.setSizes([660, 280])
        root_layout.addWidget(self.workspace_splitter, 1)

        self.setCentralWidget(root)
        self.setStyleSheet(_studio_one_stylesheet())
        self._configure_timeline_table()
        self._on_compose_part_changed()
        self._sync_phrase_range_with_bars()
        self._refresh_compose_ab_label()
        self._refresh_compose_history()
        self._refresh_history()
        self._clear_pitch_display()
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

        transport_row = QHBoxLayout()
        transport_row.setSpacing(10)
        self.playhead_label = QLabel("再生位置 1.00 小節")
        self.playhead_label.setObjectName("transportMetric")
        self.playhead_slider = QSlider(Qt.Orientation.Horizontal)
        self.playhead_slider.setRange(100, self._timeline.bars * 100)
        self.playhead_slider.setValue(100)
        self.playhead_slider.valueChanged.connect(self._on_playhead_changed)
        self.transport_tempo_label = QLabel("120 BPM / 4/4 / 16 bars")
        self.transport_tempo_label.setObjectName("transportMetric")
        transport_row.addWidget(self.playhead_label)
        transport_row.addWidget(self.playhead_slider, 1)
        transport_row.addWidget(self.transport_tempo_label)
        layout.addLayout(transport_row)

        self.status_label = QLabel("[--:--:--] 準備完了。")
        self.status_label.setObjectName("statusStrip")
        layout.addWidget(self.status_label)
        return panel

    def _build_workspace_area(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.workspace_body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_body_splitter.setChildrenCollapsible(False)

        self.arranger_editor_splitter = QSplitter(Qt.Orientation.Vertical)
        self.arranger_editor_splitter.setChildrenCollapsible(False)
        self.arranger_editor_splitter.addWidget(self._build_arranger_panel())
        self.arranger_editor_splitter.addWidget(self._build_editor_panel())
        self.arranger_editor_splitter.setSizes([620, 300])

        self.workspace_body_splitter.addWidget(self.arranger_editor_splitter)
        self.workspace_body_splitter.addWidget(self._build_inspector_panel())
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
        self.arranger_context_label = QLabel("Timeline lanes / waveform overview")
        self.arranger_context_label.setObjectName("panelCaption")
        toolbar.addWidget(self.arranger_context_label)
        toolbar.addStretch(1)

        self.add_track_button = QPushButton("トラック追加")
        self.add_midi_clip_button = QPushButton("MIDI追加")
        self.add_audio_clip_button = QPushButton("Audio追加")
        for button in (self.add_track_button, self.add_midi_clip_button, self.add_audio_clip_button):
            toolbar.addWidget(button)
        layout.addLayout(toolbar)

        self.waveform_view = WaveformView()
        self.waveform_view.setMinimumHeight(150)
        layout.addWidget(self.waveform_view)

        self.timeline_table = QTableWidget(0, self._timeline.bars)
        self.timeline_table.setObjectName("timelineTable")
        self.timeline_table.setHorizontalHeaderLabels([str(idx) for idx in range(1, self._timeline.bars + 1)])
        self.timeline_table.cellClicked.connect(self._on_timeline_cell_clicked)
        layout.addWidget(self.timeline_table, 1)

        self.add_track_button.clicked.connect(self._on_add_track)
        self.add_midi_clip_button.clicked.connect(lambda: self._on_add_clip("midi"))
        self.add_audio_clip_button.clicked.connect(lambda: self._on_add_clip("audio"))
        return box

    def _build_editor_panel(self) -> QGroupBox:
        box = QGroupBox("エディタ")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(12)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)

        self.pitch_class_label = QLabel(f"12音ガイド: {pitch_class_guide_text()}")
        self.pitch_class_label.setObjectName("panelCaption")
        self.pitch_clip_label = QLabel("選択MIDIクリップ: なし")
        self.pitch_clip_label.setObjectName("panelHeadline")
        sidebar_layout.addWidget(self.pitch_class_label)
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
        roll_caption = QLabel("Piano Roll")
        roll_caption.setObjectName("sectionLabel")
        roll_layout.addWidget(roll_caption)
        self.piano_roll_view = SimplePianoRollView()
        self.piano_roll_view.setMinimumHeight(240)
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
        self.timeline_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.timeline_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.timeline_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timeline_table.setAlternatingRowColors(False)
        self.timeline_table.setShowGrid(True)
        self.timeline_table.setWordWrap(False)
        self.timeline_table.verticalHeader().setDefaultSectionSize(42)
        self.timeline_table.verticalHeader().setMinimumWidth(180)
        self.timeline_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.timeline_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timeline_table.horizontalHeader().setMinimumSectionSize(56)

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
            lines = [
                f"選択クリップ: {clip.name}",
                f"タイプ: {'MIDI' if clip.clip_type == 'midi' else 'Audio'}",
                f"トラック: {clip.track_id}",
                f"範囲: bar {clip.start_bar}-{clip.end_bar} ({clip.length_bars} bars)",
            ]
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
        self.playhead_label.setText(f"再生位置 {self._timeline.playhead_bar:.2f} 小節")
        elapsed = self._bar_to_seconds(self._timeline.playhead_bar)
        if hasattr(self, "track_playback_position_label"):
            self.track_playback_position_label.setText(
                f"再生位置: bar {self._timeline.playhead_bar:.2f} / {elapsed:.2f}s"
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
        self.transport_tempo_label.setText(
            f"{self._tempo_bpm:.0f} BPM / {self._beats_per_bar:.0f}/4 / {self._timeline.bars} bars"
        )
        self._refresh_playback_position_labels()

    def _refresh_timeline_view(self) -> None:
        tracks = self._timeline.tracks_in_order()
        self.timeline_table.setRowCount(len(tracks))
        self.timeline_table.setColumnCount(self._timeline.bars)
        self.timeline_table.setHorizontalHeaderLabels([str(idx) for idx in range(1, self._timeline.bars + 1)])

        for row, track in enumerate(tracks):
            header_item = QTableWidgetItem(f"{track.name} ({track.track_id})")
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.timeline_table.setVerticalHeaderItem(row, header_item)
            for col in range(self._timeline.bars):
                cell = self.timeline_table.item(row, col)
                if cell is None:
                    cell = QTableWidgetItem("")
                cell.setText("")
                cell.setToolTip("")
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.timeline_table.setItem(row, col, cell)

            for clip in self._timeline.clips_for_track(track.track_id):
                self._paint_clip_on_row(row, clip)

        self._paint_playhead()
        if hasattr(self, "pitch_detail"):
            self._update_pitch_display(track_id=self._current_track_id(), bar=self._selected_timeline_bar)

    def _paint_clip_on_row(self, row: int, clip: TimelineClip) -> None:
        for bar in range(clip.start_bar, clip.end_bar + 1):
            col = bar - 1
            item = self.timeline_table.item(row, col)
            if item is None:
                continue
            if bar == clip.start_bar:
                item.setText(f"{clip.name} ({clip.clip_type})")
            item.setToolTip(f"{clip.name} | {clip.clip_type} | bar {clip.start_bar}-{clip.end_bar}")

    def _paint_playhead(self) -> None:
        bar = int(round(self._timeline.playhead_bar))
        bar = min(max(bar, 1), self._timeline.bars)
        self._refresh_playback_position_labels()
        current_track_id = self._current_track_id()
        for row, track in enumerate(self._timeline.tracks_in_order()):
            selected_row = track.track_id == current_track_id
            header_item = self.timeline_table.verticalHeaderItem(row)
            if header_item is not None:
                header_item.setBackground(QColor(41, 51, 64) if selected_row else QColor(32, 38, 47))
                header_item.setForeground(QColor(231, 236, 244) if selected_row else QColor(154, 166, 181))
            for col in range(self._timeline.bars):
                item = self.timeline_table.item(row, col)
                if item is None:
                    continue
                clip = self._find_clip_at(track.track_id, col + 1)
                is_playhead = (col + 1) == bar
                if clip is None:
                    background = QColor(28, 32, 39) if selected_row else QColor(24, 28, 34)
                    if is_playhead:
                        background = QColor(58, 43, 34) if selected_row else QColor(48, 36, 29)
                    item.setForeground(QColor(118, 128, 141))
                    item.setText("")
                else:
                    if clip.clip_type == "midi":
                        background = QColor(77, 143, 244) if clip.start_bar == col + 1 else QColor(63, 111, 186)
                    else:
                        background = QColor(217, 122, 54) if clip.start_bar == col + 1 else QColor(166, 90, 40)
                    if selected_row:
                        background = background.lighter(112)
                    if is_playhead:
                        background = background.lighter(118)
                    item.setForeground(QColor(240, 244, 250))
                item.setBackground(background)
                font = item.font()
                font.setBold(clip is not None and clip.start_bar == col + 1)
                item.setFont(font)
        self._refresh_waveform_playhead()

    def _on_playhead_changed(self, value: int) -> None:
        self._set_playhead_bar(value / 100.0, update_slider=False)

    def _set_playhead_bar(self, bar: float, update_slider: bool = True) -> None:
        self._timeline.set_playhead_bar(bar)
        playhead = self._timeline.playhead_bar
        if update_slider:
            slider_value = int(round(playhead * 100.0))
            if self.playhead_slider.value() != slider_value:
                self.playhead_slider.blockSignals(True)
                self.playhead_slider.setValue(slider_value)
                self.playhead_slider.blockSignals(False)
        self._paint_playhead()

    def _seconds_per_bar(self) -> float:
        beats_per_second = self._tempo_bpm / 60.0
        if beats_per_second <= 0:
            return 2.0
        return self._beats_per_bar / beats_per_second

    def _seconds_to_bar(self, elapsed_sec: float) -> float:
        return 1.0 + (max(elapsed_sec, 0.0) / self._seconds_per_bar())

    def _bar_to_seconds(self, bar: float) -> float:
        return max(bar - 1.0, 0.0) * self._seconds_per_bar()

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

    def _clip_note_names(self, clip: TimelineClip) -> list[str]:
        result: set[int] = set()
        for note in self._clip_note_events(clip):
            result.add(note["pitch"])
        return [midi_note_name(pitch) for pitch in sorted(result)]

    def _update_pitch_display(self, track_id: str, bar: int) -> None:
        clip = self._find_clip_at(track_id, bar)
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
        if note_events:
            ticks_per_beat = int(raw.get("ticks_per_beat", 960)) if isinstance(raw, dict) else 960
            bars = int(raw.get("bars", clip.length_bars)) if isinstance(raw, dict) else clip.length_bars
            total_ticks = max(
                max(note["start_tick"] + note["length_tick"] for note in note_events),
                max(1, bars) * max(1, ticks_per_beat) * 4,
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
            self.piano_roll_view.clear()
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
        self._update_pitch_display(track_id=clip.track_id, bar=clip.start_bar)
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
        header = self.timeline_table.verticalHeaderItem(row)
        if header is None:
            return
        text = header.text()
        if "(" not in text or not text.endswith(")"):
            return
        track_id = text[text.find("(") + 1 : -1]
        self._selected_timeline_bar = column + 1
        self.track_input.setText(track_id)
        if hasattr(self, "compose_track_input"):
            self.compose_track_input.setText(track_id)
            self._refresh_compose_history()
        self._refresh_wav_info()
        self._refresh_history()
        self._paint_playhead()
        self._update_pitch_display(track_id=track_id, bar=column + 1)
        self._set_status(f"選択トラックを {track_id} に変更しました。")

    def _on_add_track(self) -> None:
        track = self._timeline.add_track(name=f"Track {len(self._timeline.tracks)}")
        self.track_input.setText(track.track_id)
        if hasattr(self, "compose_track_input"):
            self.compose_track_input.setText(track.track_id)
            self._refresh_compose_history()
        self._refresh_timeline_view()
        self._refresh_wav_info()
        self._set_status(f"トラックを追加しました: {track.track_id}")

    def _on_add_clip(self, clip_type: str) -> None:
        track_id = self._current_track_id()
        if track_id not in self._timeline.tracks:
            self._show_error(f"トラックID '{track_id}' はタイムラインに存在しません。")
            return
        track_clips = self._timeline.clips_for_track(track_id)
        start_bar = 1 if not track_clips else min(track_clips[-1].end_bar + 1, self._timeline.bars)
        length = 4 if clip_type == "midi" else 8
        if start_bar + length - 1 > self._timeline.bars:
            self._show_error("これ以上クリップを配置できません。")
            return
        name = f"{'MIDI' if clip_type == 'midi' else 'Audio'} Clip {len(track_clips) + 1}"
        self._timeline.add_clip(track_id, clip_type, start_bar=start_bar, length_bars=length, name=name)
        self._refresh_timeline_view()
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
        self._add_audio_clip_from_wave(track_id, Path(file_path).stem, info.duration_sec)
        self._refresh_timeline_view()
        self._refresh_wav_info()
        self._set_status(
            f"WAVを読込しました: {Path(file_path).name} "
            f"({info.sample_rate}Hz, {info.duration_sec:.2f}s)"
        )

    def _add_audio_clip_from_wave(self, track_id: str, name: str, duration_sec: float) -> None:
        bars = max(1, math.ceil(duration_sec / 2.0))  # 120BPM, 4/4 を仮定
        track_clips = self._timeline.clips_for_track(track_id)
        start_bar = 1 if not track_clips else min(track_clips[-1].end_bar + 1, self._timeline.bars)
        if start_bar + bars - 1 > self._timeline.bars:
            bars = max(1, self._timeline.bars - start_bar + 1)
        self._timeline.add_clip(track_id, "audio", start_bar=start_bar, length_bars=bars, name=name)

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
                self._selected_timeline_bar = inserted.start_bar
                self.track_input.setText(inserted.track_id)
                if hasattr(self, "compose_track_input"):
                    self.compose_track_input.setText(inserted.track_id)
                self._update_pitch_display(track_id=inserted.track_id, bar=inserted.start_bar)
                self.inspector_tabs.setCurrentIndex(0)
                self._paint_playhead()
        self.utility_tabs.setCurrentWidget(self.compose_history_tab)
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
