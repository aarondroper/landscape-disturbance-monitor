import numpy as np
import pytest

from landscape_monitor.composite_prototype import (
    ReflectanceTreatment,
    apply_scale_offset,
    calculate_nbr,
    calculate_ndvi,
    index_validity_stages,
    valid_scl_mask,
)
from landscape_monitor.evaluate_reflectance_handling import (
    _assert_diagnostic_path,
    _extremes,
    _footprint_stats,
)


@pytest.mark.parametrize("mode", ReflectanceTreatment)
def test_source_nodata_remains_invalid_in_all_modes(mode):
    result = calculate_nbr(
        np.array([[np.nan, 0.2]], dtype=np.float32),
        np.array([[0.2, 0.2]], dtype=np.float32),
        treatment=mode,
    )
    assert np.isnan(result[0, 0]) and np.isfinite(result[0, 1])


def test_negative_reflectance_treatments_are_explicit():
    nir = np.array([[-0.01, 0.2]], dtype=np.float32)
    red = np.array([[0.2, 0.2]], dtype=np.float32)
    reject = calculate_ndvi(nir, red, treatment=ReflectanceTreatment.REJECT)
    preserve = calculate_ndvi(nir, red, treatment=ReflectanceTreatment.PRESERVE)
    clamp = calculate_ndvi(nir, red, treatment=ReflectanceTreatment.CLAMP_ZERO)
    assert np.isnan(reject[0, 0])
    assert np.isfinite(preserve[0, 0])
    assert clamp[0, 0] == -1.0
    stages = index_validity_stages(
        nir, red, treatment=ReflectanceTreatment.CLAMP_ZERO
    )
    assert stages["first_used"][0, 0] == 0.0
    assert stages["final_valid"][0, 0]


def test_scl_invalid_pixels_remain_invalid_in_all_modes():
    scl_valid = valid_scl_mask(np.array([[2, 9]], dtype=np.uint8))
    for mode in ReflectanceTreatment:
        result = calculate_ndvi(
            np.array([[0.4, 0.4]], dtype=np.float32),
            np.array([[0.2, 0.2]], dtype=np.float32),
            scl_valid,
            treatment=mode,
        )
        assert np.isfinite(result[0, 0]) and np.isnan(result[0, 1])


def test_positive_reflectance_is_invariant_across_modes():
    nir = np.array([[0.1, 0.7]], dtype=np.float32)
    red = np.array([[0.2, 0.1]], dtype=np.float32)
    results = [calculate_ndvi(nir, red, treatment=mode) for mode in ReflectanceTreatment]
    np.testing.assert_allclose(results[0], results[1], rtol=0, atol=1e-7)
    np.testing.assert_allclose(results[0], results[2], rtol=0, atol=1e-7)


def test_preserve_can_produce_normalized_difference_outside_bounds():
    result = calculate_nbr(
        np.array([[-0.01]], dtype=np.float32),
        np.array([[0.2]], dtype=np.float32),
        treatment=ReflectanceTreatment.PRESERVE,
    )
    assert result[0, 0] < -1


def test_clamp_zero_is_bounded_for_finite_nonnegative_inputs():
    first = np.array([[0.0, -0.2, 0.4, 1.0]], dtype=np.float32)
    second = np.array([[0.1, 0.3, 0.4, 0.0]], dtype=np.float32)
    result = calculate_nbr(first, second, treatment=ReflectanceTreatment.CLAMP_ZERO)
    assert np.all(result[np.isfinite(result)] <= 1.0 + 1e-7)
    assert np.all(result[np.isfinite(result)] >= -1.0 - 1e-7)


def test_denominator_zero_remains_invalid():
    for mode in ReflectanceTreatment:
        result = calculate_ndvi(
            np.array([[0.0]], dtype=np.float32),
            np.array([[0.0]], dtype=np.float32),
            treatment=mode,
        )
        assert np.isnan(result[0, 0])


def test_scale_offset_can_create_a_valid_negative_value():
    scaled = apply_scale_offset(np.array([500], dtype=np.uint16), 0.0001, -0.1)
    np.testing.assert_allclose(scaled, [-0.05])


def test_diagnostic_statistics_count_extreme_values():
    stats = _extremes(np.array([[-6.0, -2.1, -1.01, 0.0, 1.01, 3.0, np.nan]]))
    assert stats["less_than_minus_1"]["pixel_count"] == 3
    assert stats["greater_than_1"]["pixel_count"] == 2
    assert stats["abs_greater_than_2"]["pixel_count"] == 3
    assert stats["abs_greater_than_5"]["pixel_count"] == 1


def test_disturbance_statistics_use_only_retained_pixels():
    values = np.array([[10.0, 0.2], [0.4, np.nan]], dtype=np.float32)
    footprint = np.array([[False, True], [True, False]])
    stats = _footprint_stats(values, footprint)
    assert stats["footprint_pixel_count"] == 2
    assert stats["valid_pixel_count"] == 2
    np.testing.assert_allclose(stats["median"], 0.3)
    assert stats["outside_minus_1_to_1"]["pixel_count"] == 0


def test_diagnostic_outputs_cannot_overwrite_production_annual_paths(tmp_path):
    root = tmp_path / "diagnostics" / "reflectance"
    _assert_diagnostic_path(root / "2022" / "preserve", root)
    with pytest.raises(ValueError, match="production annual"):
        _assert_diagnostic_path(__import__("pathlib").Path("data/derived/annual/2022"), root)
