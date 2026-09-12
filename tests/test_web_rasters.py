import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin

import landscape_monitor.build_web_imagery as web_imagery
import landscape_monitor.build_web_rasters as web

ROOT = Path(__file__).parents[1]


def _small_grid(width: int = 300, height: int = 300) -> web.BrowserGrid:
    transform = from_origin(1683000, 8878000, 42.5, 42.5)
    return web.BrowserGrid(
        crs=web.BROWSER_CRS,
        transform=transform,
        width=width,
        height=height,
        bounds=tuple(
            float(value) for value in rasterio.transform.array_bounds(height, width, transform)
        ),
    )


def test_shared_analytical_grid_is_native_density_and_not_rgb_grid():
    grid = web.create_browser_grid()
    rgb_grid = web_imagery.create_browser_grid()
    assert (grid.width, grid.height) == (1272, 1241)
    assert grid.pixel_size == pytest.approx((42.49620879501987, 42.49620879501987))
    assert grid.bounds == pytest.approx(
        (1683036.2196353192, 8825702.196670972, 1737091.3972225846, 8878439.991785591)
    )
    assert (grid.width, grid.height) != (rgb_grid.width, rgb_grid.height)
    assert grid.transform == web.create_browser_grid().transform


def test_cog_is_float32_single_band_with_internal_mask_and_overview(tmp_path: Path):
    grid = _small_grid()
    values = np.full(grid.shape, 1.25, dtype=np.float32)
    valid = np.ones(grid.shape, dtype=bool)
    valid[:20, :20] = False
    values[~valid] = web.NODATA_VALUE
    path = tmp_path / "web-delivery" / "raster.tif"
    result = web.write_browser_cog(path, values, valid, grid)
    assert result["valid"] is True
    assert result["internal_mask"] is True
    assert result["overview_levels"] == web.expected_overview_levels(300, 300)
    with rasterio.open(path) as dataset:
        assert dataset.count == 1
        assert dataset.dtypes == ("float32",)
        assert dataset.nodata == -9999.0
        assert dataset.mask_flag_enums[0] == [rasterio.enums.MaskFlags.per_dataset]
        np.testing.assert_array_equal(dataset.read_masks(1)[:20, :20], 0)
        assert dataset.read(1, window=((100, 110), (100, 110))).dtype == np.dtype("float32")
        overview = dataset.read(
            1, out_shape=(150, 150), resampling=rasterio.enums.Resampling.nearest
        )
        overview_mask = dataset.read_masks(
            1, out_shape=(150, 150), resampling=rasterio.enums.Resampling.nearest
        )
        assert overview.shape == overview_mask.shape


def test_dnbr_formula_and_raw_out_of_range_float_values_are_preserved(tmp_path: Path):
    first = np.array([[0.8, web.NODATA_VALUE], [0.4, 0.7]], dtype=np.float32)
    second = np.array([[0.2, 0.1], [0.1, web.NODATA_VALUE]], dtype=np.float32)
    first_valid = first != web.NODATA_VALUE
    second_valid = second != web.NODATA_VALUE
    dnbr, valid = web.derive_dnbr(first, second, first_valid, second_valid)
    np.testing.assert_allclose(dnbr[valid], [0.6, 0.3])
    assert not valid[0, 1] and not valid[1, 1]

    grid = _small_grid(300, 300)
    values = np.full(grid.shape, 1.5, dtype=np.float32)
    values[0, 0] = -2.0
    output_valid = np.ones(grid.shape, dtype=bool)
    path = tmp_path / "web-delivery" / "float.tif"
    web.write_browser_cog(path, values, output_valid, grid)
    with rasterio.open(path) as dataset:
        readback = dataset.read(1)
        assert readback.dtype == np.dtype("float32")
        assert readback[0, 0] == pytest.approx(-2.0)
        assert readback[1, 1] == pytest.approx(1.5)


def test_bilinear_value_reprojection_uses_nearest_validity_mask():
    grid = web.create_browser_grid()
    transform = Affine(20, 0, web.SOURCE_BOUNDS[0], 0, -20, web.SOURCE_BOUNDS[3])
    values = np.full((web.SOURCE_HEIGHT, web.SOURCE_WIDTH), 0.5, dtype=np.float32)
    source_valid = np.ones(values.shape, dtype=bool)
    source_valid[:, web.SOURCE_WIDTH // 2 - 2 : web.SOURCE_WIDTH // 2 + 2] = False
    values[~source_valid] = web.NODATA_VALUE
    output, valid, nearest = web._reproject_continuous(values, source_valid, transform, grid)
    assert web.CONTINUOUS_RESAMPLING == rasterio.enums.Resampling.bilinear
    assert web.MASK_RESAMPLING == rasterio.enums.Resampling.nearest
    assert not np.any(valid & ~nearest)
    assert np.all(output[~valid] == web.NODATA_VALUE)
    assert np.all(np.isfinite(output[valid]))
    assert np.nanmin(output[valid]) >= 0.5 - 1e-5
    assert np.nanmax(output[valid]) <= 0.5 + 1e-5


def test_paths_missing_year_and_source_hashes_fail_loudly(tmp_path: Path):
    assert web.ANNUAL_YEARS == tuple(range(2017, 2027))
    with pytest.raises(FileNotFoundError):
        web._read_float_source(tmp_path / "missing-2030.tif")
    paths = web._source_paths(ROOT)
    before = web.capture_input_hashes(paths)
    assert len(before) == 24
    with pytest.raises(web.WebRasterBuildError, match="cannot target analytical"):
        web._validate_output_root(ROOT / "data" / "derived" / "disturbance", ROOT)


def test_existing_web_manifests_reconcile_without_network_or_mutation():
    paths = web._source_paths(ROOT)
    before = web.capture_input_hashes(paths)
    assert web._manifest_reconciliation(paths) == {
        "annual_years": list(range(2017, 2027)),
        "benchmark_imagery_years": [2017, 2018, 2020, 2023, 2026],
    }
    assert web.capture_input_hashes(paths) == before


def test_manifest_grid_record_is_relative_and_deterministically_serializable():
    record = web.browser_grid_record(web.create_browser_grid())
    payload = json.dumps(record, indent=2, allow_nan=False)
    assert "/home/" not in payload
    assert record["continuous_resampling"] == "bilinear"
    assert record["mask_resampling"] == "nearest"
    assert record["overview_resampling"] == "average"
    assert record["block_size"] == [256, 256]
