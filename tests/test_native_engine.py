import platform

import pytest

from music_create.audio.native_engine import NativeAudioEngine, ensure_native_library


@pytest.mark.skipif(platform.system() != "Windows", reason="native engine test is Windows-specific")
def test_build_and_load_native_engine() -> None:
    result = ensure_native_library()
    assert result.dll_path.exists()

    engine = NativeAudioEngine(auto_build=False)
    assert engine.is_available()
    assert engine.backend_id() in {"winmm", "juce"}
    assert engine.backend_name().startswith("cpp-")
    assert engine.set_backend("auto")
    assert engine.is_backend_available("winmm")
    assert engine.set_backend("winmm")
    assert engine.backend_id() == "winmm"
    assert engine.set_backend("juce")
    assert engine.backend_id() == "juce"
    assert engine.is_backend_available("juce") is False
    assert engine.set_backend("winmm")
    assert engine.start()
    assert engine.stop()
