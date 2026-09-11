import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from landscape_monitor.build_annual_series import _approved_grid
from landscape_monitor.build_recovery import _validate_raster, validate_inputs
from landscape_monitor.config import load_config
from landscape_monitor.recovery import (
    calculate_recovery,
    classify_coverage,
    distribution_fractions,
    ensure_json_safe,
    landscape_statistics,
    object_statistics,
    validate_denominators,
)

CONFIG = Path(__file__).parents[1] / "config" / "project.toml"


def test_recovery_formula_baselines_and_halfway():
    pre = np.array([[0.8, 0.8, 0.8]], dtype=np.float32)
    post = np.array([[0.2, 0.2, 0.2]], dtype=np.float32)
    current = np.array([[0.8, 0.2, 0.5]], dtype=np.float32)
    result = calculate_recovery(pre, post, current, np.ones((1, 3), dtype=np.int32))
    np.testing.assert_allclose(result, [[1.0, 0.0, 0.5]])


def test_recovery_preserves_values_above_one_and_below_zero():
    result = calculate_recovery(
        np.array([[0.8, 0.8]], dtype=np.float32),
        np.array([[0.2, 0.2]], dtype=np.float32),
        np.array([[0.95, 0.05]], dtype=np.float32),
        np.ones((1, 2), dtype=np.int32),
    )
    np.testing.assert_allclose(result, [[1.25, -0.25]])


def test_nonpositive_denominator_is_invalid():
    result = calculate_recovery(
        np.array([[0.2, 0.1]], dtype=np.float32),
        np.array([[0.2, 0.2]], dtype=np.float32),
        np.array([[0.5, 0.5]], dtype=np.float32),
        np.ones((1, 2), dtype=np.int32),
    )
    assert np.isnan(result).all()


def test_denominator_below_approved_threshold_is_detected():
    with pytest.raises(ValueError, match="below the approved dNBR threshold"):
        validate_denominators(
            np.array([[0.609]], dtype=np.float32),
            np.array([[0.31]], dtype=np.float32),
            np.ones((1, 1), dtype=np.int32),
        )


def test_current_nodata_is_invalid_and_outside_labels_is_nodata():
    result = calculate_recovery(
        np.array([[0.8, 0.8, 0.8]], dtype=np.float32),
        np.array([[0.2, 0.2, 0.2]], dtype=np.float32),
        np.array([[np.nan, 0.5, 0.5]], dtype=np.float32),
        np.array([[1, 1, 0]], dtype=np.int32),
    )
    assert np.isnan(result[0, 0])
    assert result[0, 1] == pytest.approx(0.5)
    assert np.isnan(result[0, 2])


def test_object_statistics_use_matching_labelled_pixels_and_fraction():
    labels = np.array([[1, 1, 2, 2]], dtype=np.int32)
    nbr = np.array([[0.4, np.nan, 0.6, 0.8]], dtype=np.float32)
    recovery = np.array([[0.5, np.nan, 1.2, -0.1]], dtype=np.float32)
    ndvi = np.array([[0.2, 0.3, np.nan, 0.4]], dtype=np.float32)
    records = object_statistics(labels, nbr, recovery, ndvi, pixel_area_ha=1.0)
    assert [record["disturbance_id"] for record in records] == [
        "disturbance-001",
        "disturbance-002",
    ]
    assert records[0]["nbr_valid_pixel_count"] == 1
    assert records[0]["nbr_valid_fraction"] == 0.5
    assert records[1]["recovery_median"] == pytest.approx(0.55)
    assert records[1]["ndvi_valid_pixel_count"] == 1
    assert "ndvi_recovery" not in records[0]


def test_object_coverage_boundaries_and_reporting_recommendation():
    assert classify_coverage(0.95) == "GOOD"
    assert classify_coverage(np.nextafter(0.95, 0.0)) == "USABLE_WITH_COVERAGE_FLAG"
    assert classify_coverage(0.80) == "USABLE_WITH_COVERAGE_FLAG"
    assert classify_coverage(np.nextafter(0.80, 0.0)) == "POOR"
    labels = np.ones((1, 20), dtype=np.int32)
    records = object_statistics(
        labels,
        np.array([[1] * 18 + [np.nan, np.nan]]),
        np.array([[0] * 18 + [np.nan, np.nan]]),
        np.ones((1, 20)),
    )
    assert records[0]["nbr_coverage_status"] == "USABLE_WITH_COVERAGE_FLAG"
    assert records[0]["recovery_reporting_recommended"] is True
    poor = object_statistics(
        labels,
        np.array([[1] + [np.nan] * 19]),
        np.array([[0] + [np.nan] * 19]),
        np.ones((1, 20)),
    )[0]
    assert poor["nbr_coverage_status"] == "POOR"
    assert poor["recovery_reporting_recommended"] is False


def test_zero_valid_object_year_has_null_statistics_safely():
    record = object_statistics(
        np.ones((1, 2), dtype=np.int32),
        np.full((1, 2), np.nan),
        np.full((1, 2), np.nan),
        np.full((1, 2), np.nan),
    )[0]
    assert record["recovery_valid_fraction"] == 0
    assert record["recovery_mean"] is None
    assert record["recovery_reporting_recommended"] is False
    assert record["nbr_coverage_status"] == "POOR"


def test_zero_valid_recovery_forces_poor_reporting_status():
    record = object_statistics(
        np.ones((1, 2), dtype=np.int32),
        np.ones((1, 2)),
        np.full((1, 2), np.nan),
        np.ones((1, 2)),
    )[0]
    assert record["nbr_coverage_status"] == "POOR"
    assert record["recovery_reporting_recommended"] is False


def test_landscape_threshold_fractions_use_only_valid_recovery_pixels():
    labels = np.ones((1, 4), dtype=np.int32)
    result = landscape_statistics(
        labels,
        np.ones((1, 4)),
        np.array([[0.5, 0.9, 1.1, np.nan]]),
        np.ones((1, 4)),
    )
    assert result["recovery_valid_pixel_count"] == 3
    assert result["recovery_valid_fraction"] == 0.75
    assert result["fraction_ge_050"] == pytest.approx(1.0)
    assert result["fraction_ge_080"] == pytest.approx(2 / 3)
    assert result["fraction_ge_100"] == pytest.approx(1 / 3)


def test_json_safe_has_no_nan_or_infinity():
    value = ensure_json_safe({"nan": np.nan, "infinity": float("inf"), "ok": np.float32(1.5)})
    encoded = json.dumps(value, allow_nan=False)
    assert json.loads(encoded) == {"nan": None, "infinity": None, "ok": 1.5}


def test_deterministic_object_year_ordering():
    labels = np.array([[2, 1]], dtype=np.int32)
    records = object_statistics(labels, np.ones((1, 2)), np.zeros((1, 2)), np.ones((1, 2)))
    assert [record["component_label"] for record in records] == [1, 2]


def test_distribution_categories_are_overlapping():
    fractions = distribution_fractions(np.array([-0.1, 0.5, 1.1]))
    assert fractions["fraction_lt_000"] == pytest.approx(1 / 3)
    assert fractions["fraction_ge_050"] == pytest.approx(2 / 3)
    assert fractions["fraction_ge_100"] == pytest.approx(1 / 3)
    assert fractions["fraction_gt_100"] == pytest.approx(1 / 3)


def test_mismatched_raster_grid_fails(tmp_path):
    config = load_config(CONFIG)
    grid = _approved_grid(config)
    path = tmp_path / "wrong.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:32633",
        transform=from_origin(0, 40, 20, 20),
        nodata=-9999,
    ) as dataset:
        dataset.write(np.ones((1, 2, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="dimensions"):
        _validate_raster(path, grid)


def test_missing_annual_year_fails_clearly(tmp_path):
    config = load_config(CONFIG)
    with pytest.raises(ValueError, match="annual 2017 is not COMPLETE"):
        validate_inputs(config, tmp_path / "annual", tmp_path / "disturbance")


def test_recovery_calculation_does_not_mutate_inputs():
    pre = np.array([[0.8]], dtype=np.float32)
    post = np.array([[0.2]], dtype=np.float32)
    current = np.array([[0.5]], dtype=np.float32)
    originals = (pre.copy(), post.copy(), current.copy())
    calculate_recovery(pre, post, current, np.ones((1, 1), dtype=np.int32))
    for actual, expected in zip((pre, post, current), originals):
        np.testing.assert_array_equal(actual, expected)
