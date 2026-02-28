"""Offline rendering helpers for preview/apply mix audition playback."""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

from music_create.mixing.fx import EFFECT_SPECS
from music_create.mixing.mixer_graph import MixerTrackState
from music_create.mixing.models import BuiltinEffectType

_EPSILON = 1e-6


@dataclass(slots=True)
class _WaveBuffer:
    sample_rate: int
    channels: int
    sample_width: int
    frame_count: int
    samples: list[list[float]]


def is_track_processing_active(track_state: MixerTrackState) -> bool:
    if abs(track_state.input_gain_db) > _EPSILON:
        return True
    if abs(track_state.fader_db) > _EPSILON:
        return True
    if abs(track_state.pan) > _EPSILON:
        return True

    for effect_type, fx_state in track_state.fx_chain.effects.items():
        defaults = {param.param_id: param.default for param in EFFECT_SPECS[effect_type].parameters}
        for param_id, value in fx_state.parameters.items():
            default_value = defaults.get(param_id)
            if default_value is None:
                return True
            if abs(value - default_value) > _EPSILON:
                return True
    return False


def render_track_preview_wav(
    source_path: str | Path,
    target_path: str | Path,
    track_state: MixerTrackState,
) -> Path:
    source = Path(source_path)
    target = Path(target_path)
    if not source.exists():
        raise FileNotFoundError(str(source))

    target.parent.mkdir(parents=True, exist_ok=True)
    if not is_track_processing_active(track_state):
        target.write_bytes(source.read_bytes())
        return target

    buffer = _read_wav(source)
    processed = _process_track(buffer, track_state)
    _write_wav(target, processed)
    return target


def _read_wav(path: Path) -> _WaveBuffer:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)

    if channels <= 0:
        raise ValueError("invalid channel count in wav file")
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError(f"unsupported sample width: {sample_width}")

    samples = [[] for _ in range(channels)]
    frame_size = channels * sample_width
    for frame_start in range(0, len(raw), frame_size):
        frame = raw[frame_start : frame_start + frame_size]
        if len(frame) < frame_size:
            break
        for channel in range(channels):
            offset = channel * sample_width
            chunk = frame[offset : offset + sample_width]
            samples[channel].append(_decode_one_sample(chunk, sample_width))

    return _WaveBuffer(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        frame_count=frame_count,
        samples=samples,
    )


def _write_wav(path: Path, buffer: _WaveBuffer) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(buffer.channels)
        wav.setsampwidth(buffer.sample_width)
        wav.setframerate(buffer.sample_rate)
        frames = bytearray()
        frame_count = 0
        if buffer.samples:
            frame_count = min(len(channel) for channel in buffer.samples)

        for index in range(frame_count):
            for channel in range(buffer.channels):
                sample = buffer.samples[channel][index]
                frames.extend(_encode_one_sample(sample, buffer.sample_width))

        wav.writeframes(bytes(frames))


def _process_track(buffer: _WaveBuffer, track_state: MixerTrackState) -> _WaveBuffer:
    processed: list[list[float]] = []
    input_gain = _db_to_gain(track_state.input_gain_db)

    eq_params = track_state.fx_chain.effects[BuiltinEffectType.EQ].parameters
    comp_params = track_state.fx_chain.effects[BuiltinEffectType.COMPRESSOR].parameters
    gate_params = track_state.fx_chain.effects[BuiltinEffectType.GATE].parameters
    sat_params = track_state.fx_chain.effects[BuiltinEffectType.SATURATOR].parameters

    eq_active = _effect_active(BuiltinEffectType.EQ, eq_params)
    comp_active = _effect_active(BuiltinEffectType.COMPRESSOR, comp_params)
    gate_active = _effect_active(BuiltinEffectType.GATE, gate_params)
    sat_active = _effect_active(BuiltinEffectType.SATURATOR, sat_params)

    for channel in buffer.samples:
        samples = [sample * input_gain for sample in channel]
        if eq_active:
            samples = _apply_eq(samples, buffer.sample_rate, eq_params)
        if comp_active:
            samples = _apply_compressor(samples, buffer.sample_rate, comp_params)
        if gate_active:
            samples = _apply_gate(samples, buffer.sample_rate, gate_params)
        if sat_active:
            samples = _apply_saturator(samples, sat_params)
        processed.append(samples)

    _apply_output_gain_and_pan(processed, track_state)
    for channel in processed:
        for index, sample in enumerate(channel):
            channel[index] = _clip(sample)

    return _WaveBuffer(
        sample_rate=buffer.sample_rate,
        channels=buffer.channels,
        sample_width=buffer.sample_width,
        frame_count=buffer.frame_count,
        samples=processed,
    )


def _effect_active(effect_type: BuiltinEffectType, params: dict[str, float]) -> bool:
    defaults = {param.param_id: param.default for param in EFFECT_SPECS[effect_type].parameters}
    for param_id, default_value in defaults.items():
        if abs(params.get(param_id, default_value) - default_value) > _EPSILON:
            return True
    return False


def _apply_eq(samples: list[float], sample_rate: int, params: dict[str, float]) -> list[float]:
    low_gain = _db_to_gain(params.get("low_gain_db", 0.0))
    mid_gain = _db_to_gain(params.get("mid_gain_db", 0.0))
    high_gain = _db_to_gain(params.get("high_gain_db", 0.0))
    low_freq = max(20.0, params.get("low_freq_hz", 120.0))
    high_freq = max(low_freq + 10.0, params.get("high_freq_hz", 5000.0))

    low_alpha = _one_pole_alpha(low_freq, sample_rate)
    high_alpha = _one_pole_alpha(high_freq, sample_rate)
    low_state = 0.0
    high_lp_state = 0.0

    out: list[float] = []
    for sample in samples:
        low_state = (1.0 - low_alpha) * sample + low_alpha * low_state
        high_lp_state = (1.0 - high_alpha) * sample + high_alpha * high_lp_state
        low = low_state
        high = sample - high_lp_state
        mid = sample - low - high
        out.append((low * low_gain) + (mid * mid_gain) + (high * high_gain))
    return out


def _apply_compressor(samples: list[float], sample_rate: int, params: dict[str, float]) -> list[float]:
    threshold_db = params.get("threshold_db", -18.0)
    ratio = max(1.0, params.get("ratio", 3.0))
    attack_ms = max(0.1, params.get("attack_ms", 12.0))
    release_ms = max(0.1, params.get("release_ms", 120.0))
    makeup_gain = _db_to_gain(params.get("makeup_db", 0.0))

    threshold_lin = _db_to_gain(threshold_db)
    attack_coeff = _time_coeff(attack_ms, sample_rate)
    release_coeff = _time_coeff(release_ms, sample_rate)

    env = 0.0
    out: list[float] = []
    for sample in samples:
        level = abs(sample) + 1e-12
        coeff = attack_coeff if level > env else release_coeff
        env = coeff * env + (1.0 - coeff) * level

        if env <= threshold_lin or threshold_lin <= 0.0:
            gain = 1.0
        else:
            env_db = 20.0 * math.log10(env)
            over_db = max(0.0, env_db - threshold_db)
            reduced_db = over_db / ratio
            gain_reduction_db = over_db - reduced_db
            gain = _db_to_gain(-gain_reduction_db)
        out.append(sample * gain * makeup_gain)
    return out


def _apply_gate(samples: list[float], sample_rate: int, params: dict[str, float]) -> list[float]:
    threshold = _db_to_gain(params.get("threshold_db", -40.0))
    attack_coeff = _time_coeff(max(0.1, params.get("attack_ms", 2.0)), sample_rate)
    release_coeff = _time_coeff(max(0.1, params.get("release_ms", 120.0)), sample_rate)

    env = 0.0
    gate = 0.0
    out: list[float] = []
    for sample in samples:
        level = abs(sample)
        coeff = attack_coeff if level > env else release_coeff
        env = coeff * env + (1.0 - coeff) * level

        target = 1.0 if env >= threshold else 0.0
        smooth = attack_coeff if target > gate else release_coeff
        gate = smooth * gate + (1.0 - smooth) * target
        out.append(sample * gate)
    return out


def _apply_saturator(samples: list[float], params: dict[str, float]) -> list[float]:
    drive = min(max(params.get("drive", 0.0), 0.0), 1.0)
    mix = min(max(params.get("mix", 0.0), 0.0), 1.0)
    if mix <= _EPSILON:
        return samples

    shape = 1.0 + (drive * 8.0)
    normalizer = math.tanh(shape)
    if abs(normalizer) <= _EPSILON:
        return samples

    out: list[float] = []
    for sample in samples:
        wet = math.tanh(sample * shape) / normalizer
        out.append(sample + ((wet - sample) * mix))
    return out


def _apply_output_gain_and_pan(samples: list[list[float]], track_state: MixerTrackState) -> None:
    if not samples:
        return
    output_gain = _db_to_gain(track_state.fader_db)

    if len(samples) == 1:
        channel = samples[0]
        for index, value in enumerate(channel):
            channel[index] = value * output_gain
        return

    pan = min(max(track_state.pan, -1.0), 1.0)
    angle = (pan + 1.0) * (math.pi / 4.0)
    left_gain = math.cos(angle) * output_gain
    right_gain = math.sin(angle) * output_gain

    for index, value in enumerate(samples[0]):
        samples[0][index] = value * left_gain
    for index, value in enumerate(samples[1]):
        samples[1][index] = value * right_gain
    for channel in samples[2:]:
        for index, value in enumerate(channel):
            channel[index] = value * output_gain


def _one_pole_alpha(cutoff_hz: float, sample_rate: int) -> float:
    if cutoff_hz <= 0.0 or sample_rate <= 0:
        return 0.0
    return math.exp((-2.0 * math.pi * cutoff_hz) / sample_rate)


def _time_coeff(time_ms: float, sample_rate: int) -> float:
    if time_ms <= 0.0 or sample_rate <= 0:
        return 0.0
    return math.exp(-1.0 / (time_ms * 0.001 * sample_rate))


def _db_to_gain(db: float) -> float:
    return 10 ** (db / 20.0)


def _clip(value: float) -> float:
    if value > 1.0:
        return 1.0
    if value < -1.0:
        return -1.0
    return value


def _decode_one_sample(chunk: bytes, sample_width: int) -> float:
    if sample_width == 1:
        return (chunk[0] - 128) / 128.0
    if sample_width == 2:
        value = int.from_bytes(chunk, "little", signed=True)
        return value / 32768.0
    if sample_width == 3:
        sign = b"\xff" if chunk[2] & 0x80 else b"\x00"
        value = int.from_bytes(chunk + sign, "little", signed=True)
        return value / 8388608.0
    value = int.from_bytes(chunk, "little", signed=True)
    return value / 2147483648.0


def _encode_one_sample(sample: float, sample_width: int) -> bytes:
    clipped = _clip(sample)
    if sample_width == 1:
        value = int(round((clipped * 127.5) + 128.0))
        return bytes([min(max(value, 0), 255)])
    if sample_width == 2:
        value = int(round(clipped * 32767.0))
        value = min(max(value, -32768), 32767)
        return value.to_bytes(2, "little", signed=True)
    if sample_width == 3:
        value = int(round(clipped * 8388607.0))
        value = min(max(value, -8388608), 8388607)
        return value.to_bytes(4, "little", signed=True)[:3]
    value = int(round(clipped * 2147483647.0))
    value = min(max(value, -2147483648), 2147483647)
    return value.to_bytes(4, "little", signed=True)
