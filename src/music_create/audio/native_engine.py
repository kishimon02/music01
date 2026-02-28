"""Native C++ audio core bridge for real WAV playback."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class BuildResult:
    dll_path: Path
    built: bool


class NativeAudioEngine:
    def __init__(
        self,
        dll_path: str | Path | None = None,
        auto_build: bool = True,
        preferred_backend: str | None = None,
    ) -> None:
        self._dll_path = Path(dll_path) if dll_path else default_dll_path()
        self._lib: ctypes.WinDLL | None = None
        if auto_build:
            ensure_native_library(self._dll_path)
        self._load_library()
        selected = preferred_backend or os.getenv("MUSIC_CREATE_AUDIO_BACKEND")
        if selected:
            self.set_backend(selected)

    def is_available(self) -> bool:
        return self._lib is not None

    def backend_name(self) -> str:
        if self._lib is None:
            return "unavailable"
        raw = self._lib.mc_audio_backend_name()
        return raw.decode("utf-8") if raw else "unknown"

    def backend_id(self) -> str:
        if self._lib is None:
            return "unknown"
        raw = self._lib.mc_audio_backend_id()
        return raw.decode("utf-8") if raw else "unknown"

    def set_backend(self, backend_id: str) -> bool:
        if self._lib is None:
            return False
        return bool(self._lib.mc_audio_set_backend(backend_id.encode("utf-8")))

    def is_backend_available(self, backend_id: str) -> bool:
        if self._lib is None:
            return False
        return bool(self._lib.mc_audio_is_backend_available(backend_id.encode("utf-8")))

    def start(self, sample_rate: int = 48_000, buffer_size: int = 256) -> bool:
        if self._lib is None:
            return False
        return bool(self._lib.mc_audio_start(sample_rate, buffer_size))

    def play_file(self, wav_path: str | Path) -> bool:
        if self._lib is None:
            return False
        path = str(Path(wav_path).resolve())
        return bool(self._lib.mc_audio_play_file_w(path))

    def stop_playback(self) -> bool:
        if self._lib is None:
            return False
        return bool(self._lib.mc_audio_stop_playback())

    def stop(self) -> bool:
        if self._lib is None:
            return False
        return bool(self._lib.mc_audio_stop())

    def _load_library(self) -> None:
        if not self._dll_path.exists():
            self._lib = None
            return
        dll_dirs = [self._dll_path.parent, _winget_mingw_bin_dir()]
        for directory in dll_dirs:
            if directory is None:
                continue
            if not directory.exists():
                continue
            try:
                os.add_dll_directory(str(directory))
            except Exception:
                pass
        lib = ctypes.WinDLL(str(self._dll_path))
        lib.mc_audio_start.argtypes = [ctypes.c_uint, ctypes.c_uint]
        lib.mc_audio_start.restype = ctypes.c_int
        lib.mc_audio_stop.argtypes = []
        lib.mc_audio_stop.restype = ctypes.c_int
        lib.mc_audio_is_running.argtypes = []
        lib.mc_audio_is_running.restype = ctypes.c_int
        lib.mc_audio_play_file_w.argtypes = [ctypes.c_wchar_p]
        lib.mc_audio_play_file_w.restype = ctypes.c_int
        lib.mc_audio_stop_playback.argtypes = []
        lib.mc_audio_stop_playback.restype = ctypes.c_int
        lib.mc_audio_backend_name.argtypes = []
        lib.mc_audio_backend_name.restype = ctypes.c_char_p
        lib.mc_audio_backend_id.argtypes = []
        lib.mc_audio_backend_id.restype = ctypes.c_char_p
        lib.mc_audio_set_backend.argtypes = [ctypes.c_char_p]
        lib.mc_audio_set_backend.restype = ctypes.c_int
        lib.mc_audio_is_backend_available.argtypes = [ctypes.c_char_p]
        lib.mc_audio_is_backend_available.restype = ctypes.c_int
        self._lib = lib


def default_dll_path() -> Path:
    return Path(__file__).resolve().parents[3] / "native" / "build" / "music_create_audio_core.dll"


def ensure_native_library(dll_path: str | Path | None = None) -> BuildResult:
    output_path = Path(dll_path) if dll_path else default_dll_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    compiler = _resolve_cpp_compiler()
    src_root = Path(__file__).resolve().parents[3] / "native"
    source = src_root / "audio_core" / "src" / "audio_core.cpp"
    include = src_root / "audio_core" / "include"
    header = include / "audio_core.hpp"
    if output_path.exists():
        out_time = output_path.stat().st_mtime
        if source.stat().st_mtime <= out_time and header.stat().st_mtime <= out_time:
            _copy_runtime_dlls_if_needed(output_path, compiler)
            return BuildResult(dll_path=output_path, built=False)

    command = [
        str(compiler),
        "-std=c++20",
        "-O2",
        "-shared",
        str(source),
        "-I",
        str(include),
        "-o",
        str(output_path),
        "-lwinmm",
    ]
    subprocess.run(command, check=True)
    _copy_runtime_dlls_if_needed(output_path, compiler)
    return BuildResult(dll_path=output_path, built=True)


def _resolve_cpp_compiler() -> Path:
    from shutil import which

    for candidate in [
        which("g++"),
        (
            Path.home()
            / "AppData"
            / "Local"
            / "Microsoft"
            / "WinGet"
            / "Packages"
            / "BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe"
            / "mingw64"
            / "bin"
            / "g++.exe"
        ),
        which("clang++"),
        r"C:\Program Files\LLVM\bin\clang++.exe",
    ]:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise FileNotFoundError("No supported C++ compiler found. Install WinLibs or LLVM.")


def _winget_mingw_bin_dir() -> Path | None:
    candidate = (
        Path.home()
        / "AppData"
        / "Local"
        / "Microsoft"
        / "WinGet"
        / "Packages"
        / "BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "mingw64"
        / "bin"
    )
    return candidate if candidate.exists() else None


def _copy_runtime_dlls_if_needed(output_path: Path, compiler: Path) -> None:
    compiler_dir = compiler.parent
    if not compiler.name.lower().startswith("g++"):
        return
    for dll_name in ["libstdc++-6.dll", "libgcc_s_seh-1.dll", "libwinpthread-1.dll"]:
        src = compiler_dir / dll_name
        if not src.exists():
            continue
        dst = output_path.parent / dll_name
        if dst.exists():
            continue
        shutil.copy2(src, dst)


def build_main() -> int:
    try:
        result = ensure_native_library()
    except Exception as exc:
        print(f"native build failed: {exc}")
        return 1
    print(f"native dll: {result.dll_path} (built={result.built})")
    return 0


if __name__ == "__main__":
    raise SystemExit(build_main())
