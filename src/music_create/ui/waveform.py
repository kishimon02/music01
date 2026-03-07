"""Waveform drawing widget for timeline view."""

from __future__ import annotations

from typing import Sequence

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
    from PySide6.QtWidgets import QWidget
except ImportError:  # pragma: no cover - runtime-only path
    QWidget = object  # type: ignore[assignment]
    QColor = object  # type: ignore[assignment]
    QLinearGradient = object  # type: ignore[assignment]
    QPainter = object  # type: ignore[assignment]
    QPen = object  # type: ignore[assignment]
    Qt = object  # type: ignore[assignment]


def build_waveform_envelope(samples: Sequence[float], bins: int) -> list[tuple[float, float]]:
    if bins <= 0:
        return []
    if not samples:
        return [(0.0, 0.0)] * bins

    total = len(samples)
    envelope: list[tuple[float, float]] = []
    for index in range(bins):
        start = int((index * total) / bins)
        end = int(((index + 1) * total) / bins)
        if end <= start:
            end = min(start + 1, total)
        segment = samples[start:end]
        if not segment:
            envelope.append((0.0, 0.0))
            continue
        low = max(min(min(segment), 1.0), -1.0)
        high = max(min(max(segment), 1.0), -1.0)
        envelope.append((low, high))
    return envelope


class WaveformView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._samples: list[float] = []
        self._duration_sec: float = 0.0
        self._playhead_ratio: float = 0.0
        self._has_data = False

    def clear(self) -> None:
        self._samples = []
        self._duration_sec = 0.0
        self._playhead_ratio = 0.0
        self._has_data = False
        self.update()

    def set_waveform(self, samples: Sequence[float], duration_sec: float) -> None:
        self._samples = [float(value) for value in samples]
        self._duration_sec = max(float(duration_sec), 0.0)
        self._has_data = bool(self._samples)
        self.update()

    def set_playhead_ratio(self, ratio: float) -> None:
        self._playhead_ratio = min(max(float(ratio), 0.0), 1.0)
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        outer = QLinearGradient(0, 0, 0, self.height())
        outer.setColorAt(0.0, QColor("#1B2027"))
        outer.setColorAt(1.0, QColor("#12161C"))
        painter.fillRect(self.rect(), outer)

        inner = self.rect().adjusted(8, 8, -8, -8)
        inner_fill = QLinearGradient(inner.left(), inner.top(), inner.left(), inner.bottom())
        inner_fill.setColorAt(0.0, QColor("#232A34"))
        inner_fill.setColorAt(1.0, QColor("#181D24"))
        painter.fillRect(inner, inner_fill)
        painter.setPen(QPen(QColor("#34404D"), 1))
        painter.drawRect(inner)

        center_y = inner.top() + (inner.height() / 2.0)
        for division in range(17):
            x = inner.left() + int(inner.width() * (division / 16.0))
            grid_color = QColor("#334050") if division % 4 == 0 else QColor("#28323F")
            painter.setPen(QPen(grid_color, 1))
            painter.drawLine(x, inner.top(), x, inner.bottom())

        painter.setPen(QPen(QColor("#506279"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(inner.left(), int(center_y), inner.right(), int(center_y))

        if self._has_data and inner.width() > 2:
            envelope = build_waveform_envelope(self._samples, inner.width())
            painter.setPen(QPen(QColor(45, 82, 132, 80), 2))
            for x_offset, (low, high) in enumerate(envelope):
                x = inner.left() + x_offset
                y1 = int(center_y - (high * inner.height() * 0.45))
                y2 = int(center_y - (low * inner.height() * 0.45))
                painter.drawLine(x, y1, x, y2)

            painter.setPen(QPen(QColor("#4D8FF4"), 1))
            for x_offset, (low, high) in enumerate(envelope):
                x = inner.left() + x_offset
                y1 = int(center_y - (high * inner.height() * 0.45))
                y2 = int(center_y - (low * inner.height() * 0.45))
                painter.drawLine(x, y1, x, y2)
        else:
            painter.setPen(QPen(QColor("#9AA6B5"), 1))
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, "WAV未読込")

        play_x = inner.left() + int(inner.width() * self._playhead_ratio)
        painter.setPen(QPen(QColor("#FF8A4C"), 2))
        painter.drawLine(play_x, inner.top(), play_x, inner.bottom())
