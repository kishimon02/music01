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
        QApplication,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
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
    QApplication = None  # type: ignore[assignment]
    QFileDialog = object  # type: ignore[assignment]
    QComboBox = object  # type: ignore[assignment]
    QFormLayout = object  # type: ignore[assignment]
    QGroupBox = object  # type: ignore[assignment]
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


class IntegratedWindow(QMainWindow):
    def __init__(self, mixing: Mixing | None = None) -> None:
        super().__init__()
        self.setWindowTitle("music-create 統合UI")
        self.resize(1420, 900)

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
        self._selected_midi_clip_id: str | None = None
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

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        self.main_tabs = QTabWidget()
        self.main_tabs.addTab(self._build_daw_tab(), "DAW")
        self.main_tabs.addTab(self._build_mixing_tab(), "ミキシング")
        root_layout.addWidget(self.main_tabs, 2)

        self.status_label = QLabel("準備完了。")
        root_layout.addWidget(self.status_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

    def _build_daw_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_timeline_panel())
        splitter.addWidget(self._build_compose_panel())
        splitter.setSizes([920, 500])
        layout.addWidget(splitter, 1)
        return page

    def _build_mixing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_control_panel())

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.addWidget(self._build_suggestion_panel())
        content_splitter.addWidget(self._build_history_panel())
        content_splitter.setSizes([760, 600])
        layout.addWidget(content_splitter, 1)
        return page

    def _build_control_panel(self) -> QGroupBox:
        box = QGroupBox("ミキシング操作")
        layout = QVBoxLayout(box)

        form = QFormLayout()
        self.track_input = QLineEdit("track-1")
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
        form.addRow("トラックID", self.track_input)
        form.addRow("プロファイル", self.profile_combo)
        form.addRow("提案エンジン", self.suggestion_engine_combo)
        form.addRow("解析モード", self.mode_combo)
        layout.addLayout(form)

        wav_row = QHBoxLayout()
        self.load_wav_button = QPushButton("WAV読込")
        self.play_wav_button = QPushButton("再生")
        self.stop_wav_button = QPushButton("停止")
        wav_row.addWidget(self.load_wav_button)
        wav_row.addWidget(self.play_wav_button)
        wav_row.addWidget(self.stop_wav_button)
        self.wav_info_label = QLabel("WAV未読込")
        wav_row.addWidget(self.wav_info_label, 1)
        layout.addLayout(wav_row)

        action_row = QHBoxLayout()
        self.analyze_button = QPushButton("解析")
        self.suggest_button = QPushButton("提案")
        self.preview_button = QPushButton("試聴")
        self.cancel_preview_button = QPushButton("試聴取消")
        self.apply_button = QPushButton("適用")
        self.revert_button = QPushButton("選択を巻き戻し")
        for btn in [
            self.analyze_button,
            self.suggest_button,
            self.preview_button,
            self.cancel_preview_button,
            self.apply_button,
            self.revert_button,
        ]:
            action_row.addWidget(btn)
        layout.addLayout(action_row)

        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("Dry/Wet（試聴量）"))
        self.dry_wet_slider = QSlider(Qt.Orientation.Horizontal)
        self.dry_wet_slider.setRange(0, 100)
        self.dry_wet_slider.setValue(100)
        self.dry_wet_label = QLabel("100%")
        slider_row.addWidget(self.dry_wet_slider, 1)
        slider_row.addWidget(self.dry_wet_label)
        layout.addLayout(slider_row)

        self.load_wav_button.clicked.connect(self._on_load_wav)
        self.play_wav_button.clicked.connect(self._on_play_wav)
        self.stop_wav_button.clicked.connect(self._on_stop_wav)
        self.analyze_button.clicked.connect(self._on_analyze)
        self.suggest_button.clicked.connect(self._on_suggest)
        self.preview_button.clicked.connect(self._on_preview)
        self.cancel_preview_button.clicked.connect(self._on_cancel_preview)
        self.apply_button.clicked.connect(self._on_apply)
        self.revert_button.clicked.connect(self._on_revert)
        self.dry_wet_slider.valueChanged.connect(self._on_dry_wet_changed)
        self.suggestion_engine_combo.currentIndexChanged.connect(self._on_suggestion_engine_changed)
        return box

    def _build_timeline_panel(self) -> QGroupBox:
        box = QGroupBox("DAWタイムライン")
        layout = QVBoxLayout(box)

        transport_row = QHBoxLayout()
        self.playhead_label = QLabel("再生位置: 1.00 小節")
        self.playhead_slider = QSlider(Qt.Orientation.Horizontal)
        self.playhead_slider.setRange(100, self._timeline.bars * 100)
        self.playhead_slider.setValue(100)
        self.playhead_slider.valueChanged.connect(self._on_playhead_changed)
        transport_row.addWidget(self.playhead_label)
        transport_row.addWidget(self.playhead_slider, 1)
        layout.addLayout(transport_row)

        self.waveform_view = WaveformView()
        layout.addWidget(self.waveform_view)

        clip_action_row = QHBoxLayout()
        self.add_track_button = QPushButton("トラック追加")
        self.add_midi_clip_button = QPushButton("MIDIクリップ追加")
        self.add_audio_clip_button = QPushButton("オーディオクリップ追加")
        clip_action_row.addWidget(self.add_track_button)
        clip_action_row.addWidget(self.add_midi_clip_button)
        clip_action_row.addWidget(self.add_audio_clip_button)
        layout.addLayout(clip_action_row)

        self.timeline_table = QTableWidget(0, self._timeline.bars)
        self.timeline_table.setHorizontalHeaderLabels([str(idx) for idx in range(1, self._timeline.bars + 1)])
        self.timeline_table.verticalHeader().setDefaultSectionSize(34)
        self.timeline_table.cellClicked.connect(self._on_timeline_cell_clicked)
        layout.addWidget(self.timeline_table, 1)

        pitch_box = QGroupBox("音階表示")
        pitch_layout = QVBoxLayout(pitch_box)
        self.pitch_class_label = QLabel(f"12音ガイド: {pitch_class_guide_text()}")
        self.pitch_clip_label = QLabel("選択MIDIクリップ: なし")
        self.pitch_detail = QTextEdit()
        self.pitch_detail.setReadOnly(True)
        self.pitch_detail.setMinimumHeight(90)
        self.pitch_detail.setPlaceholderText("MIDIクリップを選択すると音階（ノート名）を表示します。")
        self.piano_roll_view = SimplePianoRollView()
        pitch_layout.addWidget(self.pitch_class_label)
        pitch_layout.addWidget(self.pitch_clip_label)
        pitch_layout.addWidget(self.pitch_detail)
        pitch_layout.addWidget(self.piano_roll_view, 1)

        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("楽器:"))
        self.midi_edit_instrument_combo = QComboBox()
        for label, program in composition_instrument_options():
            self.midi_edit_instrument_combo.addItem(f"{label} ({program})", program)
        edit_row.addWidget(self.midi_edit_instrument_combo)
        edit_row.addWidget(QLabel("半音シフト:"))
        self.midi_transpose_spin = QSpinBox()
        self.midi_transpose_spin.setRange(-24, 24)
        self.midi_transpose_spin.setValue(0)
        edit_row.addWidget(self.midi_transpose_spin)
        self.midi_apply_edit_button = QPushButton("音階/楽器を反映")
        self.midi_preview_button = QPushButton("選択MIDI試聴")
        edit_row.addWidget(self.midi_apply_edit_button)
        edit_row.addWidget(self.midi_preview_button)
        pitch_layout.addLayout(edit_row)

        layout.addWidget(pitch_box)
        self._clear_pitch_display()

        self.add_track_button.clicked.connect(self._on_add_track)
        self.add_midi_clip_button.clicked.connect(lambda: self._on_add_clip("midi"))
        self.add_audio_clip_button.clicked.connect(lambda: self._on_add_clip("audio"))
        self.midi_apply_edit_button.clicked.connect(self._on_apply_midi_edit)
        self.midi_preview_button.clicked.connect(self._on_preview_selected_midi)
        return box

    def _build_suggestion_panel(self) -> QGroupBox:
        box = QGroupBox("提案比較")
        layout = QVBoxLayout(box)

        self.analysis_summary = QTextEdit()
        self.analysis_summary.setReadOnly(True)
        self.analysis_summary.setPlaceholderText("解析結果をここに表示します。")
        layout.addWidget(self.analysis_summary)

        self.suggestion_list = QListWidget()
        self.suggestion_list.currentItemChanged.connect(self._on_suggestion_selected)
        layout.addWidget(self.suggestion_list, 1)

        self.suggestion_detail = QTextEdit()
        self.suggestion_detail.setReadOnly(True)
        self.suggestion_detail.setPlaceholderText("提案詳細をここに表示します。")
        layout.addWidget(self.suggestion_detail, 1)
        return box

    def _build_history_panel(self) -> QGroupBox:
        box = QGroupBox("適用/巻き戻し履歴")
        layout = QVBoxLayout(box)

        self.history_list = QListWidget()
        self.history_list.currentItemChanged.connect(self._on_history_selected)
        layout.addWidget(self.history_list, 1)

        self.history_detail = QTextEdit()
        self.history_detail.setReadOnly(True)
        self.history_detail.setPlaceholderText("履歴詳細をここに表示します。")
        layout.addWidget(self.history_detail, 1)
        return box

    def _build_compose_panel(self) -> QGroupBox:
        box = QGroupBox("作曲支援")
        layout = QVBoxLayout(box)

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
        form.addRow("楽器", self.compose_instrument_combo)
        form.addRow("提案エンジン", self.compose_engine_combo)
        layout.addLayout(form)

        action_row = QHBoxLayout()
        self.compose_suggest_button = QPushButton("作曲提案")
        self.compose_preview_button = QPushButton("作曲試聴")
        self.compose_apply_button = QPushButton("タイムライン挿入")
        self.compose_revert_button = QPushButton("挿入を巻き戻し")
        for btn in [
            self.compose_suggest_button,
            self.compose_preview_button,
            self.compose_apply_button,
            self.compose_revert_button,
        ]:
            action_row.addWidget(btn)
        layout.addLayout(action_row)

        self.compose_suggestion_list = QListWidget()
        self.compose_suggestion_list.setToolTip("作曲提案候補（スコア順）")
        layout.addWidget(self.compose_suggestion_list, 1)

        self.compose_detail = QTextEdit()
        self.compose_detail.setReadOnly(True)
        self.compose_detail.setPlaceholderText("作曲提案の詳細をここに表示します。")
        layout.addWidget(self.compose_detail, 1)

        self.compose_history_list = QListWidget()
        self.compose_history_list.setToolTip("作曲タイムライン挿入履歴")
        layout.addWidget(self.compose_history_list, 1)

        self.compose_history_detail = QTextEdit()
        self.compose_history_detail.setReadOnly(True)
        self.compose_history_detail.setPlaceholderText("作曲挿入履歴の詳細をここに表示します。")
        layout.addWidget(self.compose_history_detail, 1)

        self.compose_part_combo.currentIndexChanged.connect(self._on_compose_part_changed)
        self.compose_track_input.editingFinished.connect(self._refresh_compose_history)
        self.compose_suggest_button.clicked.connect(self._on_compose_suggest)
        self.compose_preview_button.clicked.connect(self._on_compose_preview)
        self.compose_apply_button.clicked.connect(self._on_compose_apply)
        self.compose_revert_button.clicked.connect(self._on_compose_revert)
        self.compose_suggestion_list.currentItemChanged.connect(self._on_compose_suggestion_selected)
        self.compose_history_list.currentItemChanged.connect(self._on_compose_history_selected)
        self._on_compose_part_changed()
        self._refresh_compose_history()
        return box

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

    def _refresh_timeline_view(self) -> None:
        tracks = self._timeline.tracks_in_order()
        self.timeline_table.setRowCount(len(tracks))
        self.timeline_table.setColumnCount(self._timeline.bars)
        self.timeline_table.setHorizontalHeaderLabels([str(idx) for idx in range(1, self._timeline.bars + 1)])

        for row, track in enumerate(tracks):
            self.timeline_table.setVerticalHeaderItem(row, QTableWidgetItem(f"{track.name} ({track.track_id})"))
            for col in range(self._timeline.bars):
                cell = QTableWidgetItem("")
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.timeline_table.setItem(row, col, cell)

            for clip in self._timeline.clips_for_track(track.track_id):
                self._paint_clip_on_row(row, clip)

        self._paint_playhead()
        if hasattr(self, "pitch_detail"):
            self._clear_pitch_display()

    def _paint_clip_on_row(self, row: int, clip: TimelineClip) -> None:
        color = QColor(77, 145, 244) if clip.clip_type == "midi" else QColor(244, 145, 77)
        for bar in range(clip.start_bar, clip.end_bar + 1):
            col = bar - 1
            item = self.timeline_table.item(row, col)
            if item is None:
                continue
            item.setBackground(color)
            if bar == clip.start_bar:
                item.setText(f"{clip.name} ({clip.clip_type})")

    def _paint_playhead(self) -> None:
        bar = int(round(self._timeline.playhead_bar))
        bar = min(max(bar, 1), self._timeline.bars)
        self.playhead_label.setText(f"再生位置: {self._timeline.playhead_bar:.2f} 小節")
        self.timeline_table.clearSelection()
        for row in range(self.timeline_table.rowCount()):
            item = self.timeline_table.item(row, bar - 1)
            if item is not None:
                item.setSelected(True)
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
            return
        self.waveform_view.set_waveform(item.samples, item.duration_sec)
        self.waveform_view.set_playhead_ratio(self._playhead_ratio_for_track(track_id))

    def _clear_pitch_display(self) -> None:
        self._selected_midi_clip_id = None
        self.pitch_clip_label.setText("選択MIDIクリップ: なし")
        self.pitch_detail.setPlainText("音階: -")
        self.piano_roll_view.clear()
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
        if clip is None or clip.clip_type != "midi":
            self._clear_pitch_display()
            return
        self._selected_midi_clip_id = clip.clip_id
        raw = self._timeline.midi_clip_data.get(clip.clip_id, {})
        is_drum = bool(raw.get("is_drum")) if isinstance(raw, dict) else False
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
        else:
            self.piano_roll_view.clear()

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
        self.track_input.setText(track_id)
        if hasattr(self, "compose_track_input"):
            self.compose_track_input.setText(track_id)
            self._refresh_compose_history()
        self._refresh_wav_info()
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

    def _stop_playback_sync(self) -> None:
        self._playback_track_id = None
        self._playback_started_at = None
        self._playback_duration_sec = 0.0
        self._playback_elapsed_sec = 0.0
        if self._playback_timer is not None:
            self._playback_timer.stop()

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
            return
        self.wav_info_label.setText(f"{item.path.name} | {item.sample_rate}Hz | {item.duration_sec:.2f}s")
        self._refresh_waveform_view()

    def _on_dry_wet_changed(self, value: int) -> None:
        self.dry_wet_label.setText(f"{value}%")

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

    def _selected_compose_suggestion_id(self) -> str | None:
        item = self.compose_suggestion_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, str) else None

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
        self.compose_suggestion_list.clear()
        self.compose_detail.clear()
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

        source = self._composition.get_last_source()
        fallback = self._composition.get_last_fallback_reason()
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

    def _on_compose_apply(self) -> None:
        suggestion_id = self._selected_compose_suggestion_id()
        if suggestion_id is None:
            self._show_error("先に作曲提案を1つ選択してください。")
            return
        try:
            command_id, clip_ids = self._composition.apply_to_timeline(suggestion_id=suggestion_id)
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
                self.track_input.setText(inserted.track_id)
                if hasattr(self, "compose_track_input"):
                    self.compose_track_input.setText(inserted.track_id)
                self._update_pitch_display(track_id=inserted.track_id, bar=inserted.start_bar)
                self.main_tabs.setCurrentIndex(0)
        self._set_status(f"作曲クリップを{len(clip_ids)}件挿入しました。コマンドID={command_id}")

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
