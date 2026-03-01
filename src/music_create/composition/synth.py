"""Simple offline MIDI clip renderer for preview audition."""

from __future__ import annotations

import math
import wave
from pathlib import Path

from music_create.composition.models import GM_DRUM_NOTES, MidiClipDraft
from music_create.composition.quantize import TICKS_PER_BEAT

SAMPLE_RATE = 48_000

_INSTRUMENT_FAMILY_PRESETS: dict[str, dict[str, object]] = {
    "piano": {"harmonics": (1.0, 0.45, 0.22, 0.1), "attack": 0.002, "decay": 5.0, "sustain": 0.42, "release": 0.09},
    "chromatic": {"harmonics": (1.0, 0.65, 0.38, 0.16), "attack": 0.004, "decay": 4.2, "sustain": 0.35, "release": 0.12},
    "organ": {"harmonics": (1.0, 0.78, 0.58, 0.4), "attack": 0.001, "decay": 0.5, "sustain": 0.88, "release": 0.12},
    "guitar": {"harmonics": (1.0, 0.5, 0.3, 0.15), "attack": 0.002, "decay": 6.4, "sustain": 0.28, "release": 0.12},
    "bass": {"harmonics": (1.0, 0.22, 0.1), "attack": 0.003, "decay": 3.5, "sustain": 0.62, "release": 0.08},
    "strings": {"harmonics": (1.0, 0.35, 0.2, 0.1), "attack": 0.06, "decay": 1.6, "sustain": 0.8, "release": 0.24},
    "ensemble": {"harmonics": (1.0, 0.5, 0.32, 0.18), "attack": 0.03, "decay": 1.7, "sustain": 0.76, "release": 0.2},
    "brass": {"harmonics": (1.0, 0.58, 0.41, 0.28), "attack": 0.01, "decay": 2.8, "sustain": 0.6, "release": 0.12},
    "reed": {"harmonics": (1.0, 0.44, 0.24, 0.12), "attack": 0.008, "decay": 2.6, "sustain": 0.55, "release": 0.1},
    "pipe": {"harmonics": (1.0, 0.31, 0.16), "attack": 0.018, "decay": 2.2, "sustain": 0.66, "release": 0.14},
    "synth_lead": {"harmonics": (1.0, 0.65, 0.44, 0.28), "attack": 0.001, "decay": 1.9, "sustain": 0.72, "release": 0.09},
    "synth_pad": {"harmonics": (1.0, 0.33, 0.22, 0.12), "attack": 0.08, "decay": 1.4, "sustain": 0.78, "release": 0.3},
    "fx": {"harmonics": (1.0, 0.88, 0.65, 0.4), "attack": 0.005, "decay": 2.4, "sustain": 0.45, "release": 0.18},
}


def render_clip_to_wav(clip: MidiClipDraft, output_path: str | Path) -> Path:
    clip.validate()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    total_ticks = max((note.start_tick + note.length_tick) for note in clip.notes) if clip.notes else TICKS_PER_BEAT
    total_sec = max(_ticks_to_seconds(total_ticks) + 0.1, 0.25)
    total_samples = int(total_sec * SAMPLE_RATE)
    buffer = [0.0] * total_samples

    for note in clip.notes:
        if clip.is_drum:
            _render_drum_hit(buffer, note.pitch, note.start_tick, note.length_tick, note.velocity)
        else:
            _render_tone(
                buffer,
                note.pitch,
                note.start_tick,
                note.length_tick,
                note.velocity,
                clip.program,
            )

    _normalize(buffer, peak=0.9)
    _write_wav_int16_mono(out, buffer)
    return out


def _ticks_to_seconds(ticks: int, bpm: float = 120.0) -> float:
    beats = ticks / TICKS_PER_BEAT
    return beats * (60.0 / bpm)


def _render_tone(
    buffer: list[float],
    pitch: int,
    start_tick: int,
    length_tick: int,
    velocity: int,
    program: int | None,
) -> None:
    start_idx = int(_ticks_to_seconds(start_tick) * SAMPLE_RATE)
    duration = max(_ticks_to_seconds(length_tick), 0.04)
    length_samples = int(duration * SAMPLE_RATE)
    freq = 440.0 * (2 ** ((pitch - 69) / 12.0))
    amp = (velocity / 127.0) * 0.35
    family = _program_family(program)
    preset = _INSTRUMENT_FAMILY_PRESETS[family]
    harmonics = preset["harmonics"]  # type: ignore[assignment]
    attack = max(float(preset["attack"]), 0.001)
    decay = max(float(preset["decay"]), 0.2)
    sustain = min(max(float(preset["sustain"]), 0.05), 1.0)
    release_sec = max(float(preset["release"]), 0.03)
    release_samples = max(int(release_sec * SAMPLE_RATE), 1)
    attack_samples = max(int(attack * SAMPLE_RATE), 1)

    for i in range(length_samples):
        idx = start_idx + i
        if idx >= len(buffer):
            break
        t = i / SAMPLE_RATE
        env = _adsr_envelope(
            i=i,
            total=length_samples,
            attack_samples=attack_samples,
            decay_rate=decay,
            sustain_level=sustain,
            release_samples=release_samples,
        )
        sample = 0.0
        for harmonic_index, harmonic_level in enumerate(harmonics, start=1):
            detune = 1.0 + (0.0016 * harmonic_index if family in {"strings", "ensemble", "synth_pad"} else 0.0)
            sample += math.sin(2.0 * math.pi * freq * harmonic_index * detune * t) * float(harmonic_level)
        sample *= amp * env * 0.58
        buffer[idx] += sample


def _adsr_envelope(
    i: int,
    total: int,
    attack_samples: int,
    decay_rate: float,
    sustain_level: float,
    release_samples: int,
) -> float:
    if i < attack_samples:
        return i / attack_samples
    sustain_env = sustain_level + (1.0 - sustain_level) * math.exp(-(i - attack_samples) / (SAMPLE_RATE / decay_rate))
    if i <= total - release_samples:
        return sustain_env
    remain = max(total - i, 0)
    return sustain_env * (remain / release_samples)


def _program_family(program: int | None) -> str:
    if program is None:
        return "piano"
    normalized = min(max(int(program), 0), 127)
    if normalized <= 7:
        return "piano"
    if normalized <= 15:
        return "chromatic"
    if normalized <= 23:
        return "organ"
    if normalized <= 31:
        return "guitar"
    if normalized <= 39:
        return "bass"
    if normalized <= 47:
        return "strings"
    if normalized <= 55:
        return "ensemble"
    if normalized <= 63:
        return "brass"
    if normalized <= 71:
        return "reed"
    if normalized <= 79:
        return "pipe"
    if normalized <= 87:
        return "synth_lead"
    if normalized <= 95:
        return "synth_pad"
    return "fx"


def _render_drum_hit(buffer: list[float], pitch: int, start_tick: int, length_tick: int, velocity: int) -> None:
    start_idx = int(_ticks_to_seconds(start_tick) * SAMPLE_RATE)
    duration = max(_ticks_to_seconds(length_tick), 0.04)
    length_samples = int(duration * SAMPLE_RATE)
    amp = (velocity / 127.0) * 0.45

    for i in range(length_samples):
        idx = start_idx + i
        if idx >= len(buffer):
            break
        t = i / SAMPLE_RATE
        if pitch == GM_DRUM_NOTES["kick"]:
            freq = 90.0 - (40.0 * min(t / 0.06, 1.0))
            sample = math.sin(2.0 * math.pi * freq * t) * amp * math.exp(-t * 24.0)
        elif pitch == GM_DRUM_NOTES["snare"]:
            noise = math.sin(2.0 * math.pi * 2200.0 * t) * math.sin(2.0 * math.pi * 3200.0 * t)
            sample = noise * amp * math.exp(-t * 36.0)
        elif pitch in {GM_DRUM_NOTES["closed_hihat"], GM_DRUM_NOTES["open_hihat"]}:
            noise = math.sin(2.0 * math.pi * 6200.0 * t) * math.sin(2.0 * math.pi * 7100.0 * t)
            decay = 70.0 if pitch == GM_DRUM_NOTES["closed_hihat"] else 24.0
            sample = noise * amp * math.exp(-t * decay)
        else:
            sample = math.sin(2.0 * math.pi * 1400.0 * t) * amp * math.exp(-t * 28.0)
        buffer[idx] += sample


def _normalize(buffer: list[float], peak: float = 0.9) -> None:
    max_abs = max((abs(value) for value in buffer), default=0.0)
    if max_abs <= 1e-9:
        return
    gain = min(peak / max_abs, 1.0)
    for i, value in enumerate(buffer):
        buffer[i] = value * gain


def _write_wav_int16_mono(path: Path, buffer: list[float]) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for sample in buffer:
            clipped = min(max(sample, -1.0), 1.0)
            value = int(round(clipped * 32767.0))
            frames.extend(value.to_bytes(2, "little", signed=True))
        wav.writeframes(bytes(frames))
