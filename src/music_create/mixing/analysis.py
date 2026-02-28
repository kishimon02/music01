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
            spectral_centroid_hz=0.0,
            band_energy_low=0.0,
            band_energy_mid=0.0,
            band_energy_high=0.0,
            dynamic_range_db=0.0,
        )

    abs_samples = [abs(sample) for sample in signal]
    peak = max(abs_samples)
    mean_square = sum(sample * sample for sample in signal) / len(signal)
    rms = math.sqrt(mean_square)

    # Lightweight approximation adequate for schema and pipeline validation.
    low_bucket = sum(abs_samples[0::3])
    mid_bucket = sum(abs_samples[1::3])
    high_bucket = sum(abs_samples[2::3])
    bucket_sum = low_bucket + mid_bucket + high_bucket or 1.0

    centroid = (
        (80.0 * low_bucket + 1000.0 * mid_bucket + 6000.0 * high_bucket) / bucket_sum
        if mode == AnalysisMode.QUICK
        else (120.0 * low_bucket + 1400.0 * mid_bucket + 8000.0 * high_bucket) / bucket_sum
    )

    percentile_95 = _percentile(abs_samples, 95)
    percentile_10 = _percentile(abs_samples, 10)
    dynamic_range = _amp_to_db(percentile_95) - _amp_to_db(max(percentile_10, 1e-8))

    peak_db = _amp_to_db(peak)
    rms_db = _amp_to_db(max(rms, 1e-8))
    lufs = rms_db - 1.0  # Stable approximation placeholder.

    return TrackFeatures(
        lufs=lufs,
        peak_dbfs=peak_db,
        rms_dbfs=rms_db,
        spectral_centroid_hz=centroid,
        band_energy_low=low_bucket / bucket_sum,
        band_energy_mid=mid_bucket / bucket_sum,
        band_energy_high=high_bucket / bucket_sum,
        dynamic_range_db=dynamic_range,
    )


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
