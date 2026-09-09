import numpy as np

from landscape_monitor.composite_prototype import (
    apply_scale_offset,
    area_hectares_at_least,
    calculate_nbr,
    create_analysis_grid,
    dnbr,
    group_acquisition_items,
    median_composite,
    mosaic_valid_pixels,
    valid_count_distribution,
    valid_scl_mask,
)
from landscape_monitor.config import BBox


def test_analysis_grid_is_outward_snapped_and_aligned():
    grid = create_analysis_grid(BBox(15.12, 61.86, 15.60, 62.08))
    left, bottom, right, top = grid.bounds
    assert grid.crs == "EPSG:32633"
    assert grid.resolution == 20
    assert all(value % 20 == 0 for value in (left, bottom, right, top))
    assert grid.width == round((right - left) / 20)
    assert grid.height == round((top - bottom) / 20)
    assert grid.aoi_mask.any()


def test_scl_mask_uses_required_invalid_classes():
    scl = np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]], dtype=np.uint8)
    assert valid_scl_mask(scl).tolist() == [
        [False, False, True, False, True, True, True, True, False, False, False, False]
    ]


def test_nbr_handles_nan_and_zero_denominator():
    result = calculate_nbr(
        np.array([[3, 1, 0, np.nan, -0.1]], dtype=np.float32),
        np.array([[1, 3, 0, 1, 0.2]], dtype=np.float32),
    )
    np.testing.assert_allclose(result[0, :2], [0.5, -0.5])
    assert np.isnan(result[0, 2]) and np.isnan(result[0, 3]) and np.isnan(result[0, 4])


def test_reflectance_scale_offset_is_applied():
    result = apply_scale_offset(np.array([10000, 2000], dtype=np.uint16), 0.0001, -0.1)
    np.testing.assert_allclose(result, [0.9, 0.1], rtol=1e-6)


def test_same_date_mosaic_is_first_valid_pixel_wins():
    arrays = [np.array([[1, np.nan, 3]], dtype=np.float32), np.array([[9, 8, 7]], dtype=np.float32)]
    masks = [np.isfinite(arrays[0]), np.isfinite(arrays[1])]
    result, filled = mosaic_valid_pixels(arrays, masks)
    np.testing.assert_allclose(result, [[1, 8, 3]])
    assert filled.tolist() == [[True, True, True]]


def test_median_composite_and_valid_count_are_masked():
    composite, count = median_composite(
        [np.array([[1, np.nan]]), np.array([[3, 5]]), np.array([[2, np.nan]])]
    )
    np.testing.assert_allclose(composite, [[2, 5]], equal_nan=True)
    np.testing.assert_array_equal(count, [[3, 1]])
    stats = valid_count_distribution(count, np.ones((1, 2), dtype=bool))
    assert stats["zero_count"] == 0 and stats["max"] == 3


def test_dnbr_sign_convention():
    np.testing.assert_allclose(dnbr(np.array([[0.7]]), np.array([[0.2]])), [[0.5]])


def test_area_uses_20m_pixel_area():
    assert area_hectares_at_least(np.array([[0.1, 0.2, np.nan]]), 0.2) == {
        "pixel_count": 1,
        "area_hectares": 0.04,
    }


def test_acquisition_grouping_uses_utc_calendar_date_and_sorted_ids():
    items = [
        {"id": "b", "datetime": "2018-08-02T10:00:00Z", "mgrs_tile": "33VWJ"},
        {"id": "a", "datetime": "2018-08-01T10:00:00Z", "mgrs_tile": "33VWJ"},
        {"id": "c", "datetime": "2018-08-01T10:02:00Z", "mgrs_tile": "33VVJ"},
    ]
    groups = group_acquisition_items(items)
    assert list(groups) == ["2018-08-01", "2018-08-02"]
    assert [item["id"] for item in groups["2018-08-01"]] == ["c", "a"]
