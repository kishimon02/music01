"""Scrollable piano roll editor with a note axis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

try:
    from PySide6.QtCore import QRect, QSize, Qt
    from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
    from PySide6.QtWidgets import QHBoxLayout, QScrollBar, QWidget
except ImportError:  # pragma: no cover - runtime-only path
    QWidget = object  # type: ignore[assignment]
    QBrush = object  # type: ignore[assignment]
    QColor = object  # type: ignore[assignment]
    QHBoxLayout = object  # type: ignore[assignment]
    QLinearGradient = object  # type: ignore[assignment]
    QPainter = object  # type: ignore[assignment]
    QPen = object  # type: ignore[assignment]
    QRect = object  # type: ignore[assignment]
    QScrollBar = object  # type: ignore[assignment]
    QSize = object  # type: ignore[assignment]
    Qt = object  # type: ignore[assignment]

PITCH_CLASS_NAMES: tuple[str, ...] = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
DEFAULT_VISIBLE_PITCH_COUNT = 24
DEFAULT_PITCH_LOW = 48
DEFAULT_PITCH_HIGH = 72


@dataclass(slots=True)
class PianoRollNote:
    start_tick: int
    length_tick: int
    pitch: int
    velocity: int


def midi_pitch_name(pitch: int) -> str:
    normalized = min(max(int(pitch), 0), 127)
    octave = (normalized // 12) - 1
    return f"{PITCH_CLASS_NAMES[normalized % 12]}{octave}"


def pitch_axis_labels(low_pitch: int, high_pitch: int) -> list[str]:
    if low_pitch > high_pitch:
        low_pitch, high_pitch = high_pitch, low_pitch
    return [midi_pitch_name(pitch) for pitch in range(high_pitch, low_pitch - 1, -1)]


def roll_pitch_range(notes: Sequence[PianoRollNote]) -> tuple[int, int]:
    if not notes:
        return DEFAULT_PITCH_LOW, DEFAULT_PITCH_HIGH
    low = max(min(min(note.pitch for note in notes) - 2, 126), 0)
    high = min(max(max(note.pitch for note in notes) + 2, low + 12), 127)
    return low, high


class _PitchAxisView(QWidget):
    def __init__(self, editor: "ScrollablePianoRollEditor", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editor = editor
        self.setMinimumWidth(72)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(80, 280)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#182029"))
        inner = self.rect().adjusted(4, 8, -4, -8)
        row_height = self._editor.row_height(inner.height())
        labels = self._editor.visible_pitch_labels()

        for index, label in enumerate(labels):
            y = inner.top() + index * row_height
            pitch = self._editor.visible_pitch_range()[1] - index
            is_c = pitch % 12 == 0
            fill = QColor("#202A35" if is_c else "#1A222C")
            painter.fillRect(inner.left(), y, inner.width(), row_height, fill)
            painter.setPen(QPen(QColor("#425264" if is_c else "#2F3A45"), 1))
            painter.drawLine(inner.left(), y + row_height - 1, inner.right(), y + row_height - 1)
            painter.setPen(QPen(QColor("#E7ECF4" if is_c else "#AAB7C7"), 1))
            painter.drawText(
                QRect(inner.left() + 6, y, inner.width() - 10, row_height),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                label,
            )


class _PianoRollCanvas(QWidget):
    def __init__(self, editor: "ScrollablePianoRollEditor", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editor = editor
        self._drag_index: int | None = None
        self._drag_anchor_tick = 0
        self._drag_anchor_pitch = 60
        self._drag_origin_start = 0
        self._drag_origin_pitch = 60

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(880, 280)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        outer = QLinearGradient(0, 0, 0, self.height())
        outer.setColorAt(0.0, QColor("#1B2027"))
        outer.setColorAt(1.0, QColor("#12161C"))
        painter.fillRect(self.rect(), outer)

        inner = self._inner_rect()
        inner_fill = QLinearGradient(inner.left(), inner.top(), inner.left(), inner.bottom())
        inner_fill.setColorAt(0.0, QColor("#232A34"))
        inner_fill.setColorAt(1.0, QColor("#171C23"))
        painter.fillRect(inner, inner_fill)
        painter.setPen(QPen(QColor("#34404D"), 1))
        painter.drawRect(inner)

        row_height = self._editor.row_height(inner.height())
        visible_low, visible_high = self._editor.visible_pitch_range()

        for index, pitch in enumerate(range(visible_high, visible_low - 1, -1)):
            y = inner.top() + index * row_height
            if pitch % 12 in {1, 3, 6, 8, 10}:
                painter.fillRect(inner.left(), y, inner.width(), row_height, QColor(18, 24, 30, 78))
            painter.setPen(QPen(QColor("#506279") if pitch % 12 == 0 else QColor("#2A3440"), 1))
            painter.drawLine(inner.left(), y + row_height - 1, inner.right(), y + row_height - 1)

        for index in range(17):
            x = inner.left() + int(inner.width() * (index / 16.0))
            painter.setPen(QPen(QColor("#5A6C81") if index % 4 == 0 else QColor("#35404C"), 1))
            painter.drawLine(x, inner.top(), x, inner.bottom())

        if not self._editor.has_notes():
            painter.setPen(QPen(QColor("#9AA6B5"), 1))
            painter.drawText(inner, int(Qt.AlignmentFlag.AlignCenter), "MIDIノートなし")
            return

        painter.setPen(Qt.PenStyle.NoPen)
        for note in self._editor.notes():
            rect = self._note_rect(note)
            if rect is None:
                continue
            velocity_ratio = min(max(note.velocity / 127.0, 0.0), 1.0)
            note_fill = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
            note_fill.setColorAt(
                0.0,
                QColor(
                    int(92 + 70 * velocity_ratio),
                    int(148 + 48 * velocity_ratio),
                    255,
                    235,
                ),
            )
            note_fill.setColorAt(
                1.0,
                QColor(
                    int(46 + 40 * velocity_ratio),
                    int(92 + 36 * velocity_ratio),
                    182,
                    220,
                ),
            )
            painter.setBrush(QBrush(note_fill))
            painter.drawRoundedRect(rect, 4, 4)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if not self._editor.is_editable() or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        index = self._find_note_index_at(event.position().x(), event.position().y())
        if index is None:
            return
        tick, pitch = self._point_to_tick_pitch(event.position().x(), event.position().y())
        note = self._editor.notes()[index]
        self._drag_index = index
        self._drag_anchor_tick = tick
        self._drag_anchor_pitch = pitch
        self._drag_origin_start = note.start_tick
        self._drag_origin_pitch = note.pitch
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_index is None:
            return super().mouseMoveEvent(event)
        tick, pitch = self._point_to_tick_pitch(event.position().x(), event.position().y())
        delta_tick = tick - self._drag_anchor_tick
        delta_pitch = pitch - self._drag_anchor_pitch
        snapped_delta_tick = _snap_tick(delta_tick, step=60)
        note = self._editor.notes()[self._drag_index]
        note.start_tick = max(0, self._drag_origin_start + snapped_delta_tick)
        note.pitch = min(max(self._drag_origin_pitch + delta_pitch, 0), 127)
        self._editor.update_views()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_index is None:
            return super().mouseReleaseEvent(event)
        self._drag_index = None
        self.setCursor(Qt.CursorShape.OpenHandCursor if self._editor.is_editable() else Qt.CursorShape.ArrowCursor)
        self._editor.emit_notes_changed()
        self.update()

    def _inner_rect(self) -> QRect:
        return self.rect().adjusted(8, 8, -8, -8)

    def _note_rect(self, note: PianoRollNote) -> QRect | None:
        inner = self._inner_rect()
        visible_low, visible_high = self._editor.visible_pitch_range()
        if note.pitch < visible_low or note.pitch > visible_high:
            return None
        start_ratio = min(max(note.start_tick / self._editor.total_ticks(), 0.0), 1.0)
        end_ratio = min(max((note.start_tick + note.length_tick) / self._editor.total_ticks(), 0.0), 1.0)
        if end_ratio <= start_ratio:
            end_ratio = min(start_ratio + 0.005, 1.0)
        x = inner.left() + int(inner.width() * start_ratio)
        width = max(int(inner.width() * (end_ratio - start_ratio)), 2)
        row_height = self._editor.row_height(inner.height())
        row_index = visible_high - note.pitch
        y = inner.top() + row_index * row_height + 1
        height = max(row_height - 3, 4)
        return QRect(x, y, width, height)

    def note_rect_for_index(self, index: int) -> QRect | None:
        if index < 0 or index >= len(self._editor.notes()):
            return None
        return self._note_rect(self._editor.notes()[index])

    def _find_note_index_at(self, x: float, y: float) -> int | None:
        inner = self._inner_rect()
        if not inner.contains(int(x), int(y)):
            return None
        for index in range(len(self._editor.notes()) - 1, -1, -1):
            rect = self._note_rect(self._editor.notes()[index])
            if rect is not None and rect.contains(int(x), int(y)):
                return index
        return None

    def _point_to_tick_pitch(self, x: float, y: float) -> tuple[int, int]:
        inner = self._inner_rect()
        if inner.width() <= 1 or inner.height() <= 1:
            return 0, 60
        visible_low, visible_high = self._editor.visible_pitch_range()
        x_ratio = min(max((x - inner.left()) / inner.width(), 0.0), 1.0)
        row_height = self._editor.row_height(inner.height())
        row_index = int(min(max((y - inner.top()) / row_height, 0), self._editor.visible_pitch_count() - 1))
        tick = int(round(x_ratio * self._editor.total_ticks()))
        pitch = visible_high - row_index
        pitch = min(max(pitch, visible_low), visible_high)
        return tick, pitch


class ScrollablePianoRollEditor(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(280)
        self._notes: list[PianoRollNote] = []
        self._total_ticks = 3840
        self._editable = False
        self._on_notes_changed: Callable[[list[PianoRollNote]], None] | None = None
        self._visible_pitch_count = DEFAULT_VISIBLE_PITCH_COUNT
        self._pitch_min = 0
        self._pitch_max = 127

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.axis_view = _PitchAxisView(self)
        self.roll_canvas = _PianoRollCanvas(self)
        self.vertical_scrollbar = QScrollBar(Qt.Orientation.Vertical)
        self.vertical_scrollbar.setSingleStep(1)
        self.vertical_scrollbar.valueChanged.connect(self.update_views)

        layout.addWidget(self.axis_view, 0)
        layout.addWidget(self.roll_canvas, 1)
        layout.addWidget(self.vertical_scrollbar, 0)

        self._update_scrollbar_range()
        self.focus_pitch_range(DEFAULT_PITCH_LOW, DEFAULT_PITCH_HIGH)

    def clear(self) -> None:
        self._notes = []
        self._total_ticks = 3840
        self.focus_pitch_range(DEFAULT_PITCH_LOW, DEFAULT_PITCH_HIGH)
        self.update_views()

    def set_notes(self, notes: Sequence[PianoRollNote], total_ticks: int) -> None:
        converted: list[PianoRollNote] = []
        for note in notes:
            if isinstance(note, PianoRollNote):
                converted.append(note)
                continue
            if isinstance(note, dict):
                try:
                    converted.append(
                        PianoRollNote(
                            start_tick=int(note.get("start_tick", 0)),
                            length_tick=max(int(note.get("length_tick", 1)), 1),
                            pitch=min(max(int(note.get("pitch", 60)), 0), 127),
                            velocity=min(max(int(note.get("velocity", 90)), 1), 127),
                        )
                    )
                except (TypeError, ValueError):
                    continue
        self._notes = converted
        self._total_ticks = max(int(total_ticks), 1)
        low, high = roll_pitch_range(converted)
        self.focus_pitch_range(low, high)
        self.update_views()

    def set_editable(
        self,
        editable: bool,
        on_notes_changed: Callable[[list[PianoRollNote]], None] | None = None,
    ) -> None:
        self._editable = bool(editable)
        self._on_notes_changed = on_notes_changed
        self.roll_canvas.setCursor(Qt.CursorShape.OpenHandCursor if self._editable else Qt.CursorShape.ArrowCursor)

    def notes(self) -> list[PianoRollNote]:
        return self._notes

    def total_ticks(self) -> int:
        return self._total_ticks

    def has_notes(self) -> bool:
        return bool(self._notes)

    def is_editable(self) -> bool:
        return self._editable

    def visible_pitch_count(self) -> int:
        return self._visible_pitch_count

    def visible_pitch_range(self) -> tuple[int, int]:
        visible_high = self._pitch_max - int(self.vertical_scrollbar.value())
        visible_low = max(visible_high - self._visible_pitch_count + 1, self._pitch_min)
        if visible_low == self._pitch_min:
            visible_high = min(self._pitch_min + self._visible_pitch_count - 1, self._pitch_max)
        return visible_low, visible_high

    def visible_pitch_labels(self) -> list[str]:
        low, high = self.visible_pitch_range()
        return pitch_axis_labels(low, high)

    def focus_pitch_range(self, low_pitch: int, high_pitch: int) -> None:
        if low_pitch > high_pitch:
            low_pitch, high_pitch = high_pitch, low_pitch
        center_pitch = int(round((low_pitch + high_pitch) / 2.0))
        visible_high = min(
            max(center_pitch + (self._visible_pitch_count // 2), self._visible_pitch_count - 1),
            self._pitch_max,
        )
        value = max(min(self._pitch_max - visible_high, self.vertical_scrollbar.maximum()), self.vertical_scrollbar.minimum())
        self.vertical_scrollbar.blockSignals(True)
        self.vertical_scrollbar.setValue(value)
        self.vertical_scrollbar.blockSignals(False)

    def row_height(self, available_height: int) -> int:
        return max(int(max(available_height, self._visible_pitch_count) / self._visible_pitch_count), 12)

    def update_views(self) -> None:
        self.axis_view.update()
        self.roll_canvas.update()

    def emit_notes_changed(self) -> None:
        if self._on_notes_changed is None:
            return
        self._on_notes_changed(
            [
                PianoRollNote(
                    start_tick=note.start_tick,
                    length_tick=note.length_tick,
                    pitch=note.pitch,
                    velocity=note.velocity,
                )
                for note in self._notes
            ]
        )

    def note_rect_for_index(self, index: int) -> QRect | None:
        return self.roll_canvas.note_rect_for_index(index)

    def _update_scrollbar_range(self) -> None:
        maximum = max(self._pitch_max - self._pitch_min - self._visible_pitch_count + 1, 0)
        self.vertical_scrollbar.setRange(0, maximum)


class SimplePianoRollView(ScrollablePianoRollEditor):
    """Backward-compatible alias for the new scrollable editor."""


def _snap_tick(value: int, step: int) -> int:
    if step <= 0:
        return value
    if value >= 0:
        return int(round(value / step) * step)
    return -int(round(abs(value) / step) * step)
