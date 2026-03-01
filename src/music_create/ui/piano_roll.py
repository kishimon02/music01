"""Simple piano roll widget for visualizing MIDI note events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtWidgets import QWidget
except ImportError:  # pragma: no cover - runtime-only path
    QWidget = object  # type: ignore[assignment]
    QColor = object  # type: ignore[assignment]
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
        self.setMinimumHeight(200)
        self._notes: list[PianoRollNote] = []
        self._total_ticks: int = 3840

    def clear(self) -> None:
        self._notes = []
        self._total_ticks = 3840
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

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(19, 23, 28))

        inner = self.rect().adjusted(8, 8, -8, -8)
        painter.fillRect(inner, QColor(28, 36, 45))
        painter.setPen(QPen(QColor(66, 78, 93), 1))
        painter.drawRect(inner)

        if not self._notes:
            painter.setPen(QPen(QColor(162, 170, 182), 1))
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, "MIDIノート未選択")
            return

        low_pitch, high_pitch = roll_pitch_range(self._notes)
        pitch_span = max(high_pitch - low_pitch + 1, 1)

        # Horizontal pitch guides.
        for pitch in range(low_pitch, high_pitch + 1):
            y = inner.bottom() - int((pitch - low_pitch) / pitch_span * inner.height())
            if pitch % 12 == 0:
                painter.setPen(QPen(QColor(76, 96, 120), 1))
            else:
                painter.setPen(QPen(QColor(52, 65, 81), 1))
            painter.drawLine(inner.left(), y, inner.right(), y)

        # Vertical time guides (16 divisions).
        for idx in range(17):
            x = inner.left() + int(inner.width() * (idx / 16.0))
            color = QColor(84, 100, 122) if idx % 4 == 0 else QColor(57, 70, 88)
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
            fill = QColor(
                int(72 + 94 * velocity_ratio),
                int(128 + 80 * velocity_ratio),
                235,
                220,
            )
            painter.setBrush(fill)
            painter.drawRect(x, y, w, h)
