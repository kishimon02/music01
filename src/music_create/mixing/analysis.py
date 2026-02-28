"""Offline feature extraction used by Analyze action."""

from __future__ import annotations

import math
from concurrent.futures import Future, ThreadPoolExecutor

from music_create.mixing.models import AnalysisMode, AnalysisSnapshot, TrackFeatures

_ANALYZE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mix-analyze")


def submit_analysis_job(
    mode: AnalysisMode,
    track_signals: dict[str, list[float]],
) -> Future[AnalysisSnapshot]:
    return _ANALYZE_EXECUTOR.submit(run_analysis, mode, track_signals)


def run_analysis(mode: AnalysisMode, track_signals: dict[str, list[float]]) -> AnalysisSnapshot:
    features: dict[str, TrackFeatures] = {}
    for track_id, signal in track_signals.items():
        features[track_id] = extract_features(signal, mode)
    return AnalysisSnapshot.new(mode=mode, track_features=features)


def extract_features(signal: list[float], mode: AnalysisMode) -> TrackFeatures:
    if not signal:
        return TrackFeatures(
            lufs=-70.0,
            peak_dbfs=-70.0,
            rms_dbfs=-70.0,
            crest_factor_db=0.0,
            spectral_centroid_hz=0.0,
            band_energy_low=0.0,
            band_energy_mid=0.0,
            band_energy_high=0.0,
            dynamic_range_db=0.0,
            loudness_range_db=0.0,
            transient_density=0.0,
            zero_crossing_rate=0.0,
        )

    if mode == AnalysisMode.QUICK:
        return _extract_quick(signal)
    return _extract_full(signal)


def _extract_quick(signal: list[float]) -> TrackFeatures:
    abs_samples = [abs(sample) for sample in signal]
    peak = max(abs_samples)
    mean_square = sum(sample * sample for sample in signal) / len(signal)
    rms = math.sqrt(mean_square)

    # Fast bucket approximation used for realtime-adjacent quick mode.
    low_bucket = sum(abs_samples[0::3])
    mid_bucket = sum(abs_samples[1::3])
    high_bucket = sum(abs_samples[2::3])
    bucket_sum = low_bucket + mid_bucket + high_bucket or 1.0

    centroid = (90.0 * low_bucket + 1200.0 * mid_bucket + 6500.0 * high_bucket) / bucket_sum

    percentile_95 = _percentile(abs_samples, 95)
    percentile_10 = _percentile(abs_samples, 10)
    dynamic_range = _amp_to_db(percentile_95) - _amp_to_db(max(percentile_10, 1e-8))
    loudness_range = dynamic_range * 0.75

    peak_db = _amp_to_db(peak)
    rms_db = _amp_to_db(max(rms, 1e-8))
    lufs = rms_db - 1.0  # Stable approximation placeholder.
    crest_factor = peak_db - rms_db
    transient_density = _transient_density(signal, threshold=0.06)
    zero_crossing_rate = _zero_crossing_rate(signal)

    return TrackFeatures(
        lufs=lufs,
        peak_dbfs=peak_db,
        rms_dbfs=rms_db,
        crest_factor_db=crest_factor,
        spectral_centroid_hz=centroid,
        band_energy_low=low_bucket / bucket_sum,
        band_energy_mid=mid_bucket / bucket_sum,
        band_energy_high=high_bucket / bucket_sum,
        dynamic_range_db=dynamic_range,
        loudness_range_db=loudness_range,
        transient_density=transient_density,
        zero_crossing_rate=zero_crossing_rate,
    )


def _extract_full(signal: list[float]) -> TrackFeatures:
    abs_samples = [abs(sample) for sample in signal]
    peak = max(abs_samples)
    mean_square = sum(sample * sample for sample in signal) / len(signal)
    rms = math.sqrt(mean_square)

    low_bucket, mid_bucket, high_bucket = _full_band_energies(signal)
    bucket_sum = low_bucket + mid_bucket + high_bucket or 1.0
    centroid = (120.0 * low_bucket + 1500.0 * mid_bucket + 8000.0 * high_bucket) / bucket_sum

    percentile_95 = _percentile(abs_samples, 95)
    percentile_10 = _percentile(abs_samples, 10)
    dynamic_range = _amp_to_db(percentile_95) - _amp_to_db(max(percentile_10, 1e-8))

    frame_rms = _frame_rms(signal, frame_size=1024)
    loudness_range = _amp_to_db(_percentile(frame_rms, 95)) - _amp_to_db(max(_percentile(frame_rms, 10), 1e-8))

    peak_db = _amp_to_db(peak)
    rms_db = _amp_to_db(max(rms, 1e-8))
    lufs = rms_db - 0.5
    crest_factor = peak_db - rms_db
    transient_density = _transient_density(signal, threshold=0.04)
    zero_crossing_rate = _zero_crossing_rate(signal)

    return TrackFeatures(
        lufs=lufs,
        peak_dbfs=peak_db,
        rms_dbfs=rms_db,
        crest_factor_db=crest_factor,
        spectral_centroid_hz=centroid,
        band_energy_low=low_bucket / bucket_sum,
        band_energy_mid=mid_bucket / bucket_sum,
        band_energy_high=high_bucket / bucket_sum,
        dynamic_range_db=dynamic_range,
        loudness_range_db=loudness_range,
        transient_density=transient_density,
        zero_crossing_rate=zero_crossing_rate,
    )


def _full_band_energies(signal: list[float]) -> tuple[float, float, float]:
    low_energy = 0.0
    mid_energy = 0.0
    high_energy = 0.0
    lp = 0.0
    hp = 0.0

    # One-pole filter proxy to estimate low/mid/high components cheaply.
    for sample in signal:
        lp = 0.97 * lp + 0.03 * sample
        hp = sample - lp
        mp = sample - lp - hp * 0.4
        low_energy += abs(lp)
        mid_energy += abs(mp)
        high_energy += abs(hp)
    return low_energy, mid_energy, high_energy


def _frame_rms(signal: list[float], frame_size: int) -> list[float]:
    if frame_size <= 0:
        return [0.0]
    values: list[float] = []
    for start in range(0, len(signal), frame_size):
        frame = signal[start : start + frame_size]
        if not frame:
            continue
        energy = sum(sample * sample for sample in frame) / len(frame)
        values.append(max(math.sqrt(energy), 1e-8))
    return values or [1e-8]


def _transient_density(signal: list[float], threshold: float) -> float:
    if len(signal) < 2:
        return 0.0
    transients = 0
    for prev, cur in zip(signal, signal[1:], strict=False):
        if abs(cur - prev) >= threshold:
            transients += 1
    return transients / (len(signal) - 1)


def _zero_crossing_rate(signal: list[float]) -> float:
    if len(signal) < 2:
        return 0.0
    crossings = 0
    for prev, cur in zip(signal, signal[1:], strict=False):
        if (prev < 0 <= cur) or (prev > 0 >= cur):
            crossings += 1
    return crossings / (len(signal) - 1)


def _amp_to_db(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-8))


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = min(max(percentile, 0), 100) / 100 * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])
