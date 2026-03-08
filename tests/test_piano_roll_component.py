import os

import pytest

from music_create.ui.piano_roll import PianoRollNote, ScrollablePianoRollEditor, roll_pitch_range

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_roll_pitch_range_default_when_empty() -> None:
    assert roll_pitch_range([]) == (48, 72)


def test_roll_pitch_range_uses_note_bounds_with_margin() -> None:
    notes = [
        PianoRollNote(start_tick=0, length_tick=240, pitch=60, velocity=100),
        PianoRollNote(start_tick=240, length_tick=240, pitch=72, velocity=100),
    ]
    low, high = roll_pitch_range(notes)
    assert low <= 58
    assert high >= 74
    assert high > low


def test_scrollable_editor_focuses_selected_note_range(qapp) -> None:
    editor = ScrollablePianoRollEditor()
    try:
        editor.resize(920, 300)
        editor.show()
        qapp.processEvents()

        notes = [PianoRollNote(start_tick=0, length_tick=240, pitch=84, velocity=110)]
        editor.set_notes(notes, total_ticks=960)
        qapp.processEvents()

        low, high = editor.visible_pitch_range()
        assert low <= 84 <= high
        assert editor.vertical_scrollbar.maximum() > 0
        assert editor.visible_pitch_labels()
    finally:
        editor.close()


def test_scrollable_editor_drag_updates_note_callback(qapp) -> None:
    editor = ScrollablePianoRollEditor()
    changed: list[list[PianoRollNote]] = []
    try:
        editor.resize(920, 300)
        editor.show()
        qapp.processEvents()

        editor.set_notes([PianoRollNote(start_tick=120, length_tick=240, pitch=72, velocity=100)], total_ticks=960)
        editor.set_editable(True, lambda notes: changed.append(notes))
        qapp.processEvents()

        rect = editor.note_rect_for_index(0)
        assert rect is not None
        start = rect.center()
        end = start + QPoint(80, -24)

        QTest.mousePress(editor.roll_canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(editor.roll_canvas, end)
        QTest.mouseRelease(editor.roll_canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        qapp.processEvents()

        assert changed
        assert changed[-1][0].start_tick != 120 or changed[-1][0].pitch != 72
    finally:
        editor.close()
