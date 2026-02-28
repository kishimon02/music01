"""Integrated desktop UI: timeline, waveform analysis, and native playback."""

from __future__ import annotations

import math
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from music_create.audio.mix_render import is_track_processing_active, render_track_preview_wav
from music_create.audio.native_engine import NativeAudioEngine
from music_create.audio.repository import WaveformRepository
from music_create.mixing import Mixing
from music_create.mixing.models import Suggestion, SuggestionCommand
from music_create.mixing.service import MixingService
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
        QSlider,
        QSplitter,
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
    QSlider = object  # type: ignore[assignment]
    QSplitter = object  # type: ignore[assignment]
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
        self._timeline = TimelineState(bars=16)
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

        root_layout.addWidget(self._build_control_panel())
        root_layout.addWidget(self._build_timeline_panel(), 1)

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.addWidget(self._build_suggestion_panel())
        content_splitter.addWidget(self._build_history_panel())
        content_splitter.setSizes([760, 600])
        root_layout.addWidget(content_splitter, 1)

        self.status_label = QLabel("準備完了。")
        root_layout.addWidget(self.status_label)
        self.setCentralWidget(root)

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

        self.add_track_button.clicked.connect(self._on_add_track)
        self.add_midi_clip_button.clicked.connect(lambda: self._on_add_clip("midi"))
        self.add_audio_clip_button.clicked.connect(lambda: self._on_add_clip("audio"))
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

    def _sync_track_controls_from_timeline(self) -> None:
        current = self.track_input.text().strip()
        tracks = self._timeline.tracks_in_order()
        if not tracks:
            self.track_input.setText("track-1")
            return
        if current not in self._timeline.tracks:
            self.track_input.setText(tracks[0].track_id)

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

    def _on_timeline_cell_clicked(self, row: int, _column: int) -> None:
        header = self.timeline_table.verticalHeaderItem(row)
        if header is None:
            return
        text = header.text()
        if "(" not in text or not text.endswith(")"):
            return
        track_id = text[text.find("(") + 1 : -1]
        self.track_input.setText(track_id)
        self._refresh_wav_info()
        self._set_status(f"選択トラックを {track_id} に変更しました。")

    def _on_add_track(self) -> None:
        track = self._timeline.add_track(name=f"Track {len(self._timeline.tracks)}")
        self.track_input.setText(track.track_id)
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
