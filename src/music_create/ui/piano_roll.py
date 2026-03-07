"""Simple piano roll widget for visualizing MIDI note events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
    from PySide6.QtWidgets import QWidget
except ImportError:  # pragma: no cover - runtime-only path
    QWidget = object  # type: ignore[assignment]
    QBrush = object  # type: ignore[assignment]
    QColor = object  # type: ignore[assignment]
    QLinearGradient = object  # type: ignore[assignment]
    QPainter = object  # type: ignore[assignment]
    QPen = object  # type: ignore[assignment]
    Qt = object  # type: ignore[assignment]


@dataclass(slots=True)
class PianoRollNote:
    start_tick: int
    length_tick: int
    pitch: int
    velocity: int


def roll_pitch_range(notes: Sequence[PianoRollNote]) -> tuple[int, int]:
    if not notes:
        return 48, 72
    low = max(min(min(note.pitch for note in notes) - 2, 126), 0)
    high = min(max(max(note.pitch for note in notes) + 2, low + 12), 127)
    return low, high


class SimplePianoRollView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(240)
        self._notes: list[PianoRollNote] = []
        self._total_ticks: int = 3840
        self._editable = False
        self._on_notes_changed: Callable[[list[PianoRollNote]], None] | None = None
        self._drag_index: int | None = None
        self._drag_anchor_tick = 0
        self._drag_anchor_pitch = 60
        self._drag_origin_start = 0
        self._drag_origin_pitch = 60

    def clear(self) -> None:
        self._notes = []
        self._total_ticks = 3840
        self._drag_index = None
        self.update()

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
        self.update()

    def set_editable(
        self,
        editable: bool,
        on_notes_changed: Callable[[list[PianoRollNote]], None] | None = None,
    ) -> None:
        self._editable = bool(editable)
        self._on_notes_changed = on_notes_changed
        self.setCursor(Qt.CursorShape.OpenHandCursor if self._editable else Qt.CursorShape.ArrowCursor)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        outer = QLinearGradient(0, 0, 0, self.height())
        outer.setColorAt(0.0, QColor("#1B2027"))
        outer.setColorAt(1.0, QColor("#12161C"))
        painter.fillRect(self.rect(), outer)

        inner = self.rect().adjusted(8, 8, -8, -8)
        inner_fill = QLinearGradient(inner.left(), inner.top(), inner.left(), inner.bottom())
        inner_fill.setColorAt(0.0, QColor("#232A34"))
        inner_fill.setColorAt(1.0, QColor("#171C23"))
        painter.fillRect(inner, inner_fill)
        painter.setPen(QPen(QColor("#34404D"), 1))
        painter.drawRect(inner)

        if not self._notes:
            painter.setPen(QPen(QColor("#9AA6B5"), 1))
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, "MIDIノート未選択")
            return

        low_pitch, high_pitch = roll_pitch_range(self._notes)
        pitch_span = max(high_pitch - low_pitch + 1, 1)

        # Horizontal pitch guides.
        for pitch in range(low_pitch, high_pitch + 1):
            y = inner.bottom() - int((pitch - low_pitch) / pitch_span * inner.height())
            if pitch % 12 in {1, 3, 6, 8, 10}:
                painter.fillRect(inner.left(), y - 5, inner.width(), 10, QColor(20, 24, 30, 70))
            if pitch % 12 == 0:
                painter.setPen(QPen(QColor("#506279"), 1))
            else:
                painter.setPen(QPen(QColor("#2A3440"), 1))
            painter.drawLine(inner.left(), y, inner.right(), y)

        # Vertical time guides (16 divisions).
        for idx in range(17):
            x = inner.left() + int(inner.width() * (idx / 16.0))
            color = QColor("#5A6C81") if idx % 4 == 0 else QColor("#35404C")
            painter.setPen(QPen(color, 1))
            painter.drawLine(x, inner.top(), x, inner.bottom())

        painter.setPen(Qt.PenStyle.NoPen)
        for note in self._notes:
            start_ratio = min(max(note.start_tick / self._total_ticks, 0.0), 1.0)
            end_ratio = min(max((note.start_tick + note.length_tick) / self._total_ticks, 0.0), 1.0)
            if end_ratio <= start_ratio:
                end_ratio = min(start_ratio + 0.005, 1.0)
            x = inner.left() + int(inner.width() * start_ratio)
            w = max(int(inner.width() * (end_ratio - start_ratio)), 2)

            pitch_ratio = (note.pitch - low_pitch) / pitch_span
            y_bottom = inner.bottom() - int(inner.height() * pitch_ratio)
            h = max(int(inner.height() / pitch_span), 4)
            y = y_bottom - h

            velocity_ratio = min(max(note.velocity / 127.0, 0.0), 1.0)
            note_fill = QLinearGradient(x, y, x, y + h)
            note_fill.setColorAt(
                0.0,
                QColor(
                    int(92 + 70 * velocity_ratio),
                    int(148 + 48 * velocity_ratio),
                    255,
                    230,
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
            painter.drawRect(x, y, w, h)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if not self._editable or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        if not self._notes:
            return
        index = self._find_note_index_at(event.position().x(), event.position().y())
        if index is None:
            return
        tick, pitch = self._point_to_tick_pitch(event.position().x(), event.position().y())
        note = self._notes[index]
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
        note = self._notes[self._drag_index]
        note.start_tick = max(0, self._drag_origin_start + snapped_delta_tick)
        note.pitch = min(max(self._drag_origin_pitch + delta_pitch, 0), 127)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_index is None:
            return super().mouseReleaseEvent(event)
        self._drag_index = None
        if self._editable:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._on_notes_changed is not None:
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
        self.update()

    def _inner_rect(self):
        return self.rect().adjusted(8, 8, -8, -8)

    def _find_note_index_at(self, x: float, y: float) -> int | None:
        inner = self._inner_rect()
        if not inner.contains(int(x), int(y)):
            return None
        low_pitch, high_pitch = roll_pitch_range(self._notes)
        pitch_span = max(high_pitch - low_pitch + 1, 1)
        for idx in range(len(self._notes) - 1, -1, -1):
            note = self._notes[idx]
            start_ratio = min(max(note.start_tick / self._total_ticks, 0.0), 1.0)
            end_ratio = min(max((note.start_tick + note.length_tick) / self._total_ticks, 0.0), 1.0)
            if end_ratio <= start_ratio:
                end_ratio = min(start_ratio + 0.005, 1.0)
            nx = inner.left() + int(inner.width() * start_ratio)
            nw = max(int(inner.width() * (end_ratio - start_ratio)), 2)
            pitch_ratio = (note.pitch - low_pitch) / pitch_span
            ny_bottom = inner.bottom() - int(inner.height() * pitch_ratio)
            nh = max(int(inner.height() / pitch_span), 4)
            ny = ny_bottom - nh
            if nx <= x <= nx + nw and ny <= y <= ny + nh:
                return idx
        return None

    def _point_to_tick_pitch(self, x: float, y: float) -> tuple[int, int]:
        inner = self._inner_rect()
        low_pitch, high_pitch = roll_pitch_range(self._notes)
        pitch_span = max(high_pitch - low_pitch + 1, 1)
        if inner.width() <= 1 or inner.height() <= 1:
            return 0, 60
        x_ratio = min(max((x - inner.left()) / inner.width(), 0.0), 1.0)
        y_ratio = min(max((inner.bottom() - y) / inner.height(), 0.0), 1.0)
        tick = int(round(x_ratio * self._total_ticks))
        pitch = low_pitch + int(round(y_ratio * pitch_span))
        pitch = min(max(pitch, low_pitch), high_pitch)
        return tick, pitch


def _snap_tick(value: int, step: int) -> int:
    if step <= 0:
        return value
    if value >= 0:
        return int(round(value / step) * step)
    return -int(round(abs(value) / step) * step)
