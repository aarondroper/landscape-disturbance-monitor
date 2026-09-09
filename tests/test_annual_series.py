from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import landscape_monitor.build_annual_series as annual
from landscape_monitor.composite_prototype import AnalysisGrid, median_composite
from landscape_monitor.config import BBox, load_config


def _small_grid() -> AnalysisGrid:
    return AnalysisGrid(
        crs="EPSG:32633",
        resolution=20.0,
        transform=from_origin(500000, 500640, 20, 20),
        width=32,
        height=32,
        bounds=(500000, 500000, 500640, 500640),
        aoi_mask=np.ones((32, 32), dtype=bool),
    )


def test_exact_block_median_matches_in_memory_reference_and_counts():
    observations = [
        np.array([[1.0, np.nan], [3.0, 9.0]], dtype=np.float32),
        np.array([[5.0, 2.0], [np.nan, 7.0]], dtype=np.float32),
        np.array([[3.0, 4.0], [8.0, np.nan]], dtype=np.float32),
    ]
    expected, expected_count = median_composite(observations)
    result, result_count = annual.exact_block_median(observations)
    np.testing.assert_allclose(result, expected, equal_nan=True)
    np.testing.assert_array_equal(result_count, expected_count)
    assert result.dtype == np.float32
    assert result_count.dtype == np.uint16


def test_exact_block_median_all_nan_block_is_nan_with_zero_count():
    observations = [np.full((2, 2), np.nan, dtype=np.float32) for _ in range(4)]
    median, count = annual.exact_block_median(observations)
    assert median.dtype == np.float32
    assert np.isnan(median).all()
    assert np.all(count == 0)


def test_disk_backed_block_reduction_matches_reference(tmp_path: Path):
    grid = _small_grid()
    values = [
        np.arange(1024, dtype=np.float32).reshape(grid.shape) / 100.0,
        np.flipud(np.arange(1024, dtype=np.float32).reshape(grid.shape) / 100.0),
        np.full(grid.shape, np.nan, dtype=np.float32),
    ]
    workspace = tmp_path / "acquisitions"
    workspace.mkdir()
    acquisitions = []
    for index, value in enumerate(values):
        nbr_path = workspace / f"{index:03d}_date_nbr.tif"
        ndvi_path = workspace / f"{index:03d}_date_ndvi.tif"
        annual._write_full_temp(nbr_path, value, grid)
        annual._write_full_temp(ndvi_path, value + 0.1, grid)
        acquisitions.append(annual.TemporaryAcquisition(str(index), nbr_path, ndvi_path))

    telemetry = annual.MemoryTelemetry()
    annual._write_block_outputs(
        acquisitions,
        grid,
        tmp_path / "nbr.tif",
        tmp_path / "ndvi.tif",
        tmp_path / "count.tif",
        telemetry,
    )
    with rasterio.open(tmp_path / "nbr.tif") as dataset:
        candidate = dataset.read(1).astype(np.float32)
        candidate[candidate == dataset.nodata] = np.nan
    with rasterio.open(tmp_path / "count.tif") as dataset:
        counts = dataset.read(1)
    expected, expected_count = median_composite(values)
    np.testing.assert_allclose(candidate, expected, equal_nan=True)
    np.testing.assert_array_equal(counts, expected_count)
    assert telemetry.events[-1]["stage"] == "after block reduction"


def test_temporary_acquisition_order_is_deterministic():
    items = [
        {"id": "z", "datetime": "2019-08-03T10:00:00Z"},
        {"id": "b", "datetime": "2019-08-01T10:00:00Z"},
        {"id": "a", "datetime": "2019-08-01T09:00:00Z"},
    ]
    groups = annual.group_acquisition_items(items)
    assert list(groups) == ["2019-08-01", "2019-08-03"]
    assert [item["id"] for item in groups["2019-08-01"]] == ["a", "b"]


def test_output_grid_validation_accepts_approved_shape_and_rejects_wrong_grid(tmp_path: Path):
    grid = _small_grid()
    path = tmp_path / "grid.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=grid.width,
        height=grid.height,
        count=1,
        dtype="float32",
        crs=grid.crs,
        transform=grid.transform,
    ) as dataset:
        dataset.write(np.zeros(grid.shape, dtype=np.float32), 1)
    with rasterio.open(path) as dataset:
        annual.validate_output_grid(dataset, grid, path)

    wrong = AnalysisGrid(
        crs=grid.crs,
        resolution=grid.resolution,
        transform=grid.transform,
        width=31,
        height=32,
        bounds=grid.bounds,
        aoi_mask=np.ones((32, 31), dtype=bool),
    )
    with rasterio.open(path) as dataset:
        with pytest.raises(ValueError, match="dimensions"):
            annual.validate_output_grid(dataset, wrong, path)


def test_cli_requires_explicit_year_and_has_no_all_mode():
    with pytest.raises(SystemExit):
        annual.parse_args([])
    with pytest.raises(SystemExit):
        annual.parse_args(["--all"])
    assert annual.parse_args(["--year", "2019"]).year == 2019


def test_unsupported_year_fails_clearly():
    config = load_config(Path("config/project.toml"))
    with pytest.raises(ValueError, match="unsupported year"):
        annual._build_interval(config, 1900)


def test_annual_build_api_requires_one_year_argument():
    assert "year" in annual.build.__annotations__
    with pytest.raises(TypeError):
        annual.build(Path("config/project.toml"), Path("missing.json"), Path("out"), Path("tmp"))


def test_temporary_workspace_cleans_only_its_own_run(tmp_path: Path):
    root = tmp_path / "annual" / "2019"
    unrelated = root / "keep-me.txt"
    root.mkdir(parents=True)
    unrelated.write_text("preserve", encoding="utf-8")
    with annual.temporary_workspace(root, 2019) as workspace:
        (workspace / "temporary.bin").write_bytes(b"derived")
        assert workspace.exists()
    assert not workspace.exists()
    assert unrelated.read_text(encoding="utf-8") == "preserve"


def test_approved_grid_dimensions_regression():
    grid = annual.create_analysis_grid(BBox(15.12, 61.86, 15.60, 62.08))
    assert grid.bounds == annual.APPROVED_BOUNDS
    assert (grid.width, grid.height) == (annual.APPROVED_WIDTH, annual.APPROVED_HEIGHT)
