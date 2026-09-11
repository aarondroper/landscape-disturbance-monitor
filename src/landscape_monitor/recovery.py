"""Pure local helpers for pixel and object-level NBR spectral recovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

PIXEL_AREA_HECTARES = 0.04
GOOD_MIN = 0.95
USABLE_MIN = 0.80
RECOVERY_NODATA = -9999.0


def _same_shape(*arrays: np.ndarray) -> tuple[int, ...]:
    shape = np.asarray(arrays[0]).shape
    if any(np.asarray(array).shape != shape for array in arrays[1:]):
        raise ValueError("recovery arrays must share a shape")
    return shape


def finite_values(values: np.ndarray, nodata: float | int | None = None) -> np.ndarray:
    """Return a finite-value mask, excluding an explicitly encoded nodata value."""
    array = np.asarray(values)
    valid = np.isfinite(array)
    if nodata is not None:
        valid &= array != nodata
    return valid


def calculate_recovery(
    nbr_2017: np.ndarray,
    nbr_2018: np.ndarray,
    nbr_year: np.ndarray,
    labels: np.ndarray | None = None,
    nodata: float | int | None = None,
) -> np.ndarray:
    """Calculate unbounded NBR recovery, returning NaN for invalid pixels.

    The positive-denominator check is intentionally separate from the approved
    ``>= 0.30`` disturbance consistency check.  This lets tests and diagnostics
    expose a positive but below-threshold denominator instead of silently
    changing it.
    """
    _same_shape(nbr_2017, nbr_2018, nbr_year)
    pre = np.asarray(nbr_2017, dtype=np.float64)
    post = np.asarray(nbr_2018, dtype=np.float64)
    current = np.asarray(nbr_year, dtype=np.float64)
    valid = (
        finite_values(pre, nodata)
        & finite_values(post, nodata)
        & finite_values(current, nodata)
    )
    if labels is not None:
        _same_shape(nbr_2017, labels)
        valid &= np.asarray(labels) > 0
    denominator = pre - post
    valid &= np.isfinite(denominator) & (denominator > 0)
    result = np.full(pre.shape, np.nan, dtype=np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        values = (current - post) / denominator
    valid &= np.isfinite(values)
    result[valid] = values[valid].astype(np.float32)
    return result


def classify_coverage(valid_fraction: float) -> str:
    """Return the project QA category using exact approved boundaries."""
    value = float(valid_fraction)
    if not np.isfinite(value):
        raise ValueError("valid_fraction must be finite")
    if value >= GOOD_MIN:
        return "GOOD"
    if value >= USABLE_MIN:
        return "USABLE_WITH_COVERAGE_FLAG"
    return "POOR"


def _percentiles(values: np.ndarray) -> dict[str, float | None]:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return {"mean": None, "median": None, "p10": None, "p90": None, "min": None, "max": None}
    return {
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "p10": float(np.percentile(finite, 10)),
        "p90": float(np.percentile(finite, 90)),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
    }


def distribution_fractions(values: np.ndarray) -> dict[str, float | None]:
    """Return overlapping threshold fractions among valid recovery values."""
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return {
            "fraction_lt_000": None,
            "fraction_ge_000": None,
            "fraction_ge_050": None,
            "fraction_ge_080": None,
            "fraction_ge_100": None,
            "fraction_gt_100": None,
        }
    count = float(finite.size)
    return {
        "fraction_lt_000": float(np.count_nonzero(finite < 0) / count),
        "fraction_ge_000": float(np.count_nonzero(finite >= 0) / count),
        "fraction_ge_050": float(np.count_nonzero(finite >= 0.50) / count),
        "fraction_ge_080": float(np.count_nonzero(finite >= 0.80) / count),
        "fraction_ge_100": float(np.count_nonzero(finite >= 1.00) / count),
        "fraction_gt_100": float(np.count_nonzero(finite > 1.00) / count),
    }


def denominator_diagnostics(
    nbr_2017: np.ndarray,
    nbr_2018: np.ndarray,
    labels: np.ndarray,
    baseline_nbr_min: float = 0.30,
    dnbr_min: float = 0.30,
) -> dict[str, Any]:
    """Summarize the recovery denominator inside retained labelled pixels."""
    _same_shape(nbr_2017, nbr_2018, labels)
    retained = np.asarray(labels) > 0
    pre = np.asarray(nbr_2017, dtype=np.float64)
    post = np.asarray(nbr_2018, dtype=np.float64)
    pair = retained & finite_values(pre) & finite_values(post)
    denominator = pre - post
    values = denominator[pair]
    finite = values[np.isfinite(values)]
    if finite.size:
        percentiles = {
            "min": float(np.min(finite)),
            "p1": float(np.percentile(finite, 1)),
            "median": float(np.median(finite)),
            "p99": float(np.percentile(finite, 99)),
            "max": float(np.max(finite)),
        }
        boundary = {
            "exactly_at_threshold": int(np.count_nonzero(finite == dnbr_min)),
            "within_1e-7_below_threshold": int(
                np.count_nonzero((finite < dnbr_min) & (finite >= dnbr_min - 1e-7))
            ),
            "within_1e-6_of_threshold": int(
                np.count_nonzero(np.isclose(finite, dnbr_min, rtol=0, atol=1e-6))
            ),
        }
        counts = {
            "less_equal_zero": int(np.count_nonzero(finite <= 0)),
            "less_than_dnbr_min": int(np.count_nonzero(finite < dnbr_min)),
            "greater_equal_dnbr_min": int(np.count_nonzero(finite >= dnbr_min)),
        }
        baseline_violations = int(np.count_nonzero(pre[pair] <= baseline_nbr_min))
    else:
        percentiles = {key: None for key in ("min", "p1", "median", "p99", "max")}
        boundary = {
            "exactly_at_threshold": 0,
            "within_1e-7_below_threshold": 0,
            "within_1e-6_of_threshold": 0,
        }
        counts = {
            "less_equal_zero": 0,
            "less_than_dnbr_min": 0,
            "greater_equal_dnbr_min": 0,
        }
        baseline_violations = 0
    return {
        "retained_disturbance_pixel_count": int(np.count_nonzero(retained)),
        "valid_baseline_pair_pixel_count": int(np.count_nonzero(pair)),
        "invalid_baseline_pair_pixel_count": int(np.count_nonzero(retained & ~pair)),
        "baseline_nbr_min": float(baseline_nbr_min),
        "dnbr_min": float(dnbr_min),
        "baseline_nbr_criterion_violations": baseline_violations,
        "denominator_statistics": percentiles,
        "denominator_counts": counts,
        "threshold_boundary_checks": boundary,
    }


def validate_denominators(
    nbr_2017: np.ndarray,
    nbr_2018: np.ndarray,
    labels: np.ndarray,
    baseline_nbr_min: float = 0.30,
    dnbr_min: float = 0.30,
) -> dict[str, Any]:
    """Validate that labelled baseline pixels satisfy the fixed disturbance rule."""
    diagnostics = denominator_diagnostics(
        nbr_2017, nbr_2018, labels, baseline_nbr_min=baseline_nbr_min, dnbr_min=dnbr_min
    )
    counts = diagnostics["denominator_counts"]
    if diagnostics["invalid_baseline_pair_pixel_count"]:
        raise ValueError("retained disturbance pixels contain invalid 2017/2018 NBR baseline pairs")
    if diagnostics["baseline_nbr_criterion_violations"]:
        raise ValueError("retained disturbance pixels violate the NBR_2017 baseline criterion")
    if counts["less_than_dnbr_min"]:
        raise ValueError(
            f"retained disturbance pixels contain {counts['less_than_dnbr_min']} "
            f"denominators below the approved dNBR threshold {dnbr_min}"
        )
    return diagnostics


def _object_indices(labels: np.ndarray) -> list[tuple[int, np.ndarray]]:
    label_array = np.asarray(labels)
    return [
        (label, np.flatnonzero(label_array.ravel() == label))
        for label in sorted(int(value) for value in np.unique(label_array) if value > 0)
    ]


def object_statistics(
    labels: np.ndarray,
    nbr: np.ndarray,
    recovery: np.ndarray,
    ndvi: np.ndarray,
    *,
    object_metadata: Mapping[int, Mapping[str, Any]] | None = None,
    pixel_area_ha: float = PIXEL_AREA_HECTARES,
) -> list[dict[str, Any]]:
    """Aggregate one year from the actual pixels carrying each label."""
    _same_shape(labels, nbr, recovery, ndvi)
    label_array = np.asarray(labels)
    nbr_flat = np.asarray(nbr, dtype=np.float64).ravel()
    recovery_flat = np.asarray(recovery, dtype=np.float64).ravel()
    ndvi_flat = np.asarray(ndvi, dtype=np.float64).ravel()
    records: list[dict[str, Any]] = []
    for label, indices in _object_indices(label_array):
        nbr_values = nbr_flat[indices]
        recovery_values = recovery_flat[indices]
        ndvi_values = ndvi_flat[indices]
        nbr_valid = np.isfinite(nbr_values)
        recovery_valid = np.isfinite(recovery_values)
        ndvi_valid = np.isfinite(ndvi_values)
        total = int(indices.size)
        nbr_count = int(np.count_nonzero(nbr_valid))
        recovery_count = int(np.count_nonzero(recovery_valid))
        ndvi_count = int(np.count_nonzero(ndvi_valid))
        nbr_stats = _percentiles(nbr_values[nbr_valid])
        recovery_stats = _percentiles(recovery_values[recovery_valid])
        coverage_status = classify_coverage(nbr_count / total) if total else "POOR"
        if recovery_count == 0:
            coverage_status = "POOR"
        record: dict[str, Any] = {
            "component_label": label,
            "disturbance_id": f"disturbance-{label:03d}",
            "year": None,
            "area_ha": float(total * pixel_area_ha),
            "total_pixel_count": total,
            "nbr_valid_pixel_count": nbr_count,
            "nbr_valid_fraction": float(nbr_count / total) if total else 0.0,
            "nbr_valid_area_ha": float(nbr_count * pixel_area_ha),
            "nbr_missing_area_ha": float((total - nbr_count) * pixel_area_ha),
            "nbr_coverage_status": coverage_status,
            "nbr_mean": nbr_stats["mean"],
            "nbr_median": nbr_stats["median"],
            "nbr_p10": nbr_stats["p10"],
            "nbr_p90": nbr_stats["p90"],
            "recovery_valid_pixel_count": recovery_count,
            "recovery_valid_fraction": float(recovery_count / total) if total else 0.0,
            "recovery_mean": recovery_stats["mean"],
            "recovery_median": recovery_stats["median"],
            "recovery_p10": recovery_stats["p10"],
            "recovery_p90": recovery_stats["p90"],
            "recovery_min": recovery_stats["min"],
            "recovery_max": recovery_stats["max"],
            "recovery_reporting_recommended": coverage_status != "POOR",
            "ndvi_valid_pixel_count": ndvi_count,
            "ndvi_valid_fraction": float(ndvi_count / total) if total else 0.0,
            "ndvi_median": float(np.median(ndvi_values[ndvi_valid])) if ndvi_count else None,
            "ndvi_p10": float(np.percentile(ndvi_values[ndvi_valid], 10)) if ndvi_count else None,
            "ndvi_p90": float(np.percentile(ndvi_values[ndvi_valid], 90)) if ndvi_count else None,
        }
        record.update(distribution_fractions(recovery_values[recovery_valid]))
        if object_metadata and label in object_metadata:
            record["disturbance_id"] = str(object_metadata[label]["disturbance_id"])
            record["area_ha"] = float(object_metadata[label]["area_ha"])
        records.append(record)
    return records


def landscape_statistics(
    labels: np.ndarray,
    nbr: np.ndarray,
    recovery: np.ndarray,
    ndvi: np.ndarray,
    *,
    pixel_area_ha: float = PIXEL_AREA_HECTARES,
) -> dict[str, Any]:
    """Aggregate one year over all retained disturbance pixels."""
    _same_shape(labels, nbr, recovery, ndvi)
    retained = np.asarray(labels) > 0
    total = int(np.count_nonzero(retained))
    nbr_values = np.asarray(nbr, dtype=np.float64)[retained]
    recovery_values = np.asarray(recovery, dtype=np.float64)[retained]
    ndvi_values = np.asarray(ndvi, dtype=np.float64)[retained]
    nbr_values = nbr_values[np.isfinite(nbr_values)]
    recovery_values = recovery_values[np.isfinite(recovery_values)]
    ndvi_values = ndvi_values[np.isfinite(ndvi_values)]
    nbr_stats = _percentiles(nbr_values)
    recovery_stats = _percentiles(recovery_values)
    ndvi_stats = _percentiles(ndvi_values)
    record: dict[str, Any] = {
        "total_disturbance_pixel_count": total,
        "valid_nbr_pixel_count": int(nbr_values.size),
        "valid_nbr_fraction": float(nbr_values.size / total) if total else 0.0,
        "valid_nbr_area_ha": float(nbr_values.size * pixel_area_ha),
        "missing_nbr_area_ha": float((total - nbr_values.size) * pixel_area_ha),
        "nbr_mean": nbr_stats["mean"],
        "nbr_median": nbr_stats["median"],
        "nbr_p10": nbr_stats["p10"],
        "nbr_p90": nbr_stats["p90"],
        "recovery_valid_pixel_count": int(recovery_values.size),
        "recovery_valid_fraction": float(recovery_values.size / total) if total else 0.0,
        "recovery_mean": recovery_stats["mean"],
        "recovery_median": recovery_stats["median"],
        "recovery_p10": recovery_stats["p10"],
        "recovery_p90": recovery_stats["p90"],
        "recovery_min": recovery_stats["min"],
        "recovery_max": recovery_stats["max"],
        "ndvi_valid_pixel_count": int(ndvi_values.size),
        "ndvi_valid_fraction": float(ndvi_values.size / total) if total else 0.0,
        "ndvi_median": ndvi_stats["median"],
    }
    record.update(
        {
            key: value
            for key, value in distribution_fractions(recovery_values).items()
            if key
            in {
                "fraction_lt_000",
                "fraction_ge_050",
                "fraction_ge_080",
                "fraction_ge_100",
                "fraction_gt_100",
            }
        }
    )
    return record


def json_safe(value: Any) -> Any:
    """Recursively reject non-standard JSON numbers and normalize NumPy scalars."""
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError("analysis contains a non-finite JSON number")
        return value
    return value


def ensure_json_safe(value: Any) -> Any:
    """Return JSON-safe data, converting internal NaN statistics to null."""
    if isinstance(value, Mapping):
        return {str(key): ensure_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [ensure_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return json_safe(value)
