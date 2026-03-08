"""Qt Quick bridge objects used by the arranger-first workspace."""

from __future__ import annotations

from typing import Any

from music_create.ui.transport_display import (
    DISPLAY_MODE_BARS,
    DEFAULT_TICKS_PER_BEAT,
    bar_to_seconds,
    format_clock_time,
    format_ruler_label,
    format_transport_position,
)

try:
    from PySide6.QtCore import QObject, Property, Signal, Slot
except ImportError:  # pragma: no cover - runtime-only path
    QObject = object  # type: ignore[assignment]

    def Property(*_args, **_kwargs):  # type: ignore[misc]
        return None

    def Slot(*_args, **_kwargs):  # type: ignore[misc]
        def decorator(func):
            return func

        return decorator

    class Signal:  # type: ignore[override]
        def __init__(self, *_args, **_kwargs) -> None:
            return None


class WorkspaceLayoutState(QObject):
    changed = Signal()

    def __init__(
        self,
        *,
        inspector_collapsed: bool = False,
        rack_collapsed: bool = False,
        display_mode: str = DISPLAY_MODE_BARS,
        zoom_level: int = 16,
    ) -> None:
        super().__init__()
        self._inspector_collapsed = bool(inspector_collapsed)
        self._rack_collapsed = bool(rack_collapsed)
        self._display_mode = display_mode
        self._zoom_level = int(zoom_level)

    def get_inspector_collapsed(self) -> bool:
        return self._inspector_collapsed

    def get_rack_collapsed(self) -> bool:
        return self._rack_collapsed

    def get_display_mode(self) -> str:
        return self._display_mode

    def get_zoom_level(self) -> int:
        return self._zoom_level

    def set_inspector_collapsed(self, collapsed: bool) -> None:
        value = bool(collapsed)
        if value == self._inspector_collapsed:
            return
        self._inspector_collapsed = value
        self.changed.emit()

    def set_rack_collapsed(self, collapsed: bool) -> None:
        value = bool(collapsed)
        if value == self._rack_collapsed:
            return
        self._rack_collapsed = value
        self.changed.emit()

    def set_display_mode(self, display_mode: str) -> None:
        if display_mode == self._display_mode:
            return
        self._display_mode = display_mode
        self.changed.emit()

    def set_zoom_level(self, zoom_level: int) -> None:
        value = int(zoom_level)
        if value == self._zoom_level:
            return
        self._zoom_level = value
        self.changed.emit()

    inspectorCollapsed = Property(bool, get_inspector_collapsed, notify=changed)
    rackCollapsed = Property(bool, get_rack_collapsed, notify=changed)
    displayMode = Property(str, get_display_mode, notify=changed)
    zoomLevel = Property(int, get_zoom_level, notify=changed)


class TransportState(QObject):
    changed = Signal()
    playheadRequested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self._playhead_text = "001.01.000"
        self._tempo_text = "120 BPM / 4/4"
        self._range_text = "64 bars"
        self._playhead_value = 100
        self._playhead_maximum = 6400

    def sync(
        self,
        *,
        playhead_bar: float,
        total_bars: int,
        display_mode: str,
        tempo_bpm: float,
        beats_per_bar: float,
    ) -> None:
        self._playhead_text = format_transport_position(
            playhead_bar,
            display_mode=display_mode,
            tempo_bpm=tempo_bpm,
            beats_per_bar=beats_per_bar,
            ticks_per_beat=DEFAULT_TICKS_PER_BEAT,
        )
        self._tempo_text = f"{tempo_bpm:.0f} BPM / {beats_per_bar:.0f}/4"
        if display_mode == DISPLAY_MODE_BARS:
            self._range_text = f"{total_bars} bars"
        else:
            total_seconds = bar_to_seconds(float(total_bars + 1), tempo_bpm, beats_per_bar)
            self._range_text = format_clock_time(
                total_seconds,
                always_include_hours=total_seconds >= 3600.0,
                include_millis=False,
            )
        self._playhead_value = int(round(playhead_bar * 100.0))
        self._playhead_maximum = max(int(total_bars) * 100, 100)
        self.changed.emit()

    def get_playhead_text(self) -> str:
        return self._playhead_text

    def get_tempo_text(self) -> str:
        return self._tempo_text

    def get_range_text(self) -> str:
        return self._range_text

    def get_playhead_value(self) -> int:
        return self._playhead_value

    def get_playhead_maximum(self) -> int:
        return self._playhead_maximum

    @Slot(int, name="requestPlayheadFromSlider")
    def request_playhead_from_slider(self, slider_value: int) -> None:
        self.playheadRequested.emit(max(float(slider_value), 100.0) / 100.0)

    playheadText = Property(str, get_playhead_text, notify=changed)
    tempoText = Property(str, get_tempo_text, notify=changed)
    rangeText = Property(str, get_range_text, notify=changed)
    playheadValue = Property(int, get_playhead_value, notify=changed)
    playheadMaximum = Property(int, get_playhead_maximum, notify=changed)


class TimelineSceneModel(QObject):
    sceneChanged = Signal()
    selectionRequested = Signal(str, int, str)
    clipCreationRequested = Signal(str, int, int, int)
    zoomInRequested = Signal()
    zoomOutRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._tracks: list[dict[str, Any]] = []
        self._total_bars = 64
        self._content_end_bar = 1
        self._max_bars = 1000
        self._playhead_bar = 1.0
        self._selected_track_id = ""
        self._selected_bar = 1
        self._selected_clip_id = ""
        self._zoom_level = 16
        self._display_mode = DISPLAY_MODE_BARS
        self._tempo_bpm = 120.0
        self._beats_per_bar = 4.0
        self._tool_mode = "select"

    def sync(
        self,
        *,
        tracks: list[dict[str, Any]],
        total_bars: int,
        content_end_bar: int,
        max_bars: int,
        playhead_bar: float,
        selected_track_id: str,
        selected_bar: int,
        selected_clip_id: str,
        zoom_level: int,
        display_mode: str,
        tempo_bpm: float,
        beats_per_bar: float,
        tool_mode: str,
    ) -> None:
        self._tracks = tracks
        self._total_bars = int(total_bars)
        self._content_end_bar = int(content_end_bar)
        self._max_bars = int(max_bars)
        self._playhead_bar = float(playhead_bar)
        self._selected_track_id = selected_track_id
        self._selected_bar = int(selected_bar)
        self._selected_clip_id = selected_clip_id
        self._zoom_level = int(zoom_level)
        self._display_mode = display_mode
        self._tempo_bpm = float(tempo_bpm)
        self._beats_per_bar = float(beats_per_bar)
        self._tool_mode = tool_mode
        self.sceneChanged.emit()

    def get_tracks(self) -> list[dict[str, Any]]:
        return self._tracks

    def get_total_bars(self) -> int:
        return self._total_bars

    def get_content_end_bar(self) -> int:
        return self._content_end_bar

    def get_max_bars(self) -> int:
        return self._max_bars

    def get_playhead_bar(self) -> float:
        return self._playhead_bar

    def get_selected_track_id(self) -> str:
        return self._selected_track_id

    def get_selected_bar(self) -> int:
        return self._selected_bar

    def get_selected_clip_id(self) -> str:
        return self._selected_clip_id

    def get_zoom_level(self) -> int:
        return self._zoom_level

    def get_display_mode(self) -> str:
        return self._display_mode

    def get_tool_mode(self) -> str:
        return self._tool_mode

    @Slot(int, result=str, name="rulerLabel")
    def ruler_label(self, bar_number: int) -> str:
        return format_ruler_label(
            int(bar_number),
            display_mode=self._display_mode,
            tempo_bpm=self._tempo_bpm,
            beats_per_bar=self._beats_per_bar,
        )

    @Slot(str, int, str, name="requestSelection")
    def request_selection(self, track_id: str, bar: int, clip_id: str = "") -> None:
        self.selectionRequested.emit(track_id, max(int(bar), 1), clip_id)

    @Slot(str, int, int, int, name="requestClipCreation")
    def request_clip_creation(self, track_id: str, start_bar: int, end_bar: int, lane_index: int) -> None:
        normalized_start = max(int(start_bar), 1)
        normalized_end = max(int(end_bar), normalized_start)
        self.clipCreationRequested.emit(track_id, normalized_start, normalized_end, int(lane_index))

    @Slot(name="requestZoomIn")
    def request_zoom_in(self) -> None:
        self.zoomInRequested.emit()

    @Slot(name="requestZoomOut")
    def request_zoom_out(self) -> None:
        self.zoomOutRequested.emit()

    @Slot(str, name="setToolMode")
    def set_tool_mode(self, tool_mode: str) -> None:
        normalized = tool_mode if tool_mode in {"select", "pencil"} else "select"
        if normalized == self._tool_mode:
            return
        self._tool_mode = normalized
        self.sceneChanged.emit()

    tracks = Property("QVariantList", get_tracks, notify=sceneChanged)
    totalBars = Property(int, get_total_bars, notify=sceneChanged)
    contentEndBar = Property(int, get_content_end_bar, notify=sceneChanged)
    maxBars = Property(int, get_max_bars, notify=sceneChanged)
    playheadBar = Property(float, get_playhead_bar, notify=sceneChanged)
    selectedTrackId = Property(str, get_selected_track_id, notify=sceneChanged)
    selectedBar = Property(int, get_selected_bar, notify=sceneChanged)
    selectedClipId = Property(str, get_selected_clip_id, notify=sceneChanged)
    zoomLevel = Property(int, get_zoom_level, notify=sceneChanged)
    displayMode = Property(str, get_display_mode, notify=sceneChanged)
    toolMode = Property(str, get_tool_mode, notify=sceneChanged)
