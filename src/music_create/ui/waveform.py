"""Waveform drawing widget for timeline view."""

from __future__ import annotations

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
        self.setMinimumHeight(130)
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
        painter.fillRect(self.rect(), QColor(20, 24, 31))

        inner = self.rect().adjusted(8, 8, -8, -8)
        painter.fillRect(inner, QColor(27, 34, 45))
        painter.setPen(QPen(QColor(58, 70, 88), 1))
        painter.drawRect(inner)

        center_y = inner.top() + (inner.height() / 2.0)
        painter.setPen(QPen(QColor(70, 86, 110), 1, Qt.PenStyle.DashLine))
        painter.drawLine(inner.left(), int(center_y), inner.right(), int(center_y))

        if self._has_data and inner.width() > 2:
            envelope = build_waveform_envelope(self._samples, inner.width())
            painter.setPen(QPen(QColor(92, 180, 255), 1))
            for x_offset, (low, high) in enumerate(envelope):
                x = inner.left() + x_offset
                y1 = int(center_y - (high * inner.height() * 0.45))
                y2 = int(center_y - (low * inner.height() * 0.45))
                painter.drawLine(x, y1, x, y2)
        else:
            painter.setPen(QPen(QColor(150, 160, 175), 1))
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, "WAV未読込")

        play_x = inner.left() + int(inner.width() * self._playhead_ratio)
        painter.setPen(QPen(QColor(255, 118, 77), 2))
        painter.drawLine(play_x, inner.top(), play_x, inner.bottom())

