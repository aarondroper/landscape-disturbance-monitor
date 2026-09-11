import numpy as np
import pytest

from landscape_monitor.composite_prototype import (
    ReflectanceTreatment,
    calculate_nbr,
    calculate_ndvi,
    index_validity_stages,
)
from landscape_monitor.diagnose_annual_coverage import (
    REASON_CODES,
    _assert_diagnostic_path,
    _write_json,
    attribute_missingness,
    rescued_pixels,
    union_observations,
)


def test_validity_stage_counting_separates_source_negative_and_denominator():
    first = np.array([[0.0, -0.1, np.nan, 0.0]], dtype=np.float32)
    second = np.array([[0.0, 0.2, 0.1, 0.0]], dtype=np.float32)
    scl_valid = np.array([[True, True, True, False]])
    stages = index_validity_stages(first, second, scl_valid)

    assert stages["source_valid"].tolist() == [[True, True, False, False]]
    assert stages["negative_rejected"].tolist() == [[False, True, False, False]]
    assert stages["before_denominator"].tolist() == [[True, False, False, False]]
    assert stages["denominator_failure"].tolist() == [[True, False, False, False]]
    assert stages["final_valid"].tolist() == [[False, False, False, False]]


def test_missingness_attribution_is_mutually_exclusive_with_documented_precedence():
    aoi = np.ones((1, 6), dtype=bool)
    categories, reason_map = attribute_missingness(
        aoi_mask=aoi,
        scl_valid=np.array([[True, False, True, True, True, True]]),
        required_source_valid=np.array([[True, True, False, True, True, True]]),
        before_denominator=np.array([[True, False, False, False, True, False]]),
        denominator_failure=np.array([[False, False, False, False, True, True]]),
        final_valid=np.array([[True, False, False, False, False, False]]),
    )
    assert [value["pixel_count"] for value in categories.values()] == [1, 1, 1, 1, 1]
    assert reason_map.tolist() == [[0, 1, 2, 3, 4, 5]]
    assert sum(value["pixel_count"] for value in categories.values()) == 5


def test_union_of_observations_is_aoi_clipped_and_deterministic():
    aoi = np.array([[True, True, False]])
    states = [
        {"valid": np.array([[True, False, True]])},
        {"valid": np.array([[False, True, True]])},
    ]
    np.testing.assert_array_equal(
        union_observations(states, "valid", aoi), np.array([[True, True, False]])
    )


def test_negative_reflectance_what_if_and_rescued_pixels():
    nir = np.array([[-0.01, 0.2, np.nan]], dtype=np.float32)
    swir2 = np.array([[0.2, 0.2, 0.2]], dtype=np.float32)
    scl = np.ones((1, 3), dtype=bool)
    current = np.isfinite(calculate_nbr(nir, swir2, scl))
    what_if = np.isfinite(
        calculate_nbr(nir, swir2, scl, treatment=ReflectanceTreatment.PRESERVE)
    )
    np.testing.assert_array_equal(current, [[False, True, False]])
    np.testing.assert_array_equal(what_if, [[True, True, False]])
    np.testing.assert_array_equal(
        rescued_pixels(current, what_if, np.ones((1, 3), dtype=bool)), [[True, False, False]]
    )


def test_denominator_failure_attribution_is_reported():
    stages = index_validity_stages(
        np.array([[0.0, 0.2]], dtype=np.float32),
        np.array([[0.0, 0.2]], dtype=np.float32),
        np.ones((1, 2), dtype=bool),
    )
    assert stages["before_denominator"].tolist() == [[True, True]]
    assert stages["denominator_failure"].tolist() == [[True, False]]
    assert stages["final_valid"].tolist() == [[False, True]]


def test_diagnostic_extensions_do_not_change_production_defaults_or_ordering():
    nir = np.array([[0.1, -0.1]], dtype=np.float32)
    red = np.array([[0.2, 0.2]], dtype=np.float32)
    mask = np.ones((1, 2), dtype=bool)
    np.testing.assert_array_equal(
        calculate_ndvi(nir, red, mask),
        calculate_ndvi(nir, red, mask, treatment=ReflectanceTreatment.REJECT),
    )
    assert list(REASON_CODES) == [
        "valid",
        "never_scl_valid",
        "scl_valid_but_required_source_never_valid",
        "source_valid_but_always_rejected_by_negative_reflectance",
        "denominator_or_non_finite_failure",
        "mixed_or_other",
    ]


def test_generated_summary_json_is_deterministically_key_sorted(tmp_path):
    path = tmp_path / "summary.json"
    _write_json(path, {"2023": {"b": 1}, "2022": {"a": 1}})
    assert path.read_text(encoding="utf-8").startswith('{\n  "2022"')


def test_coverage_diagnostic_cannot_write_production_annual_paths(tmp_path):
    _assert_diagnostic_path(tmp_path / "coverage")
    with pytest.raises(ValueError, match="production annual"):
        _assert_diagnostic_path(__import__("pathlib").Path("data/derived/annual/2022"))
