from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import landscape_monitor.build_web_imagery as web

CONFIG = Path(__file__).parents[1] / "config" / "project.toml"


def _small_grid(width: int = 600, height: int = 600) -> web.BrowserGrid:
    transform = from_origin(1683000, 8878000, 21.25, 21.25)
    return web.BrowserGrid(
        crs=web.BROWSER_CRS,
        transform=transform,
        width=width,
        height=height,
        bounds=tuple(
            float(value) for value in rasterio.transform.array_bounds(height, width, transform)
        ),
        pixel_size_x=21.25,
        pixel_size_y=21.25,
    )


def test_browser_grid_is_derived_once_from_approved_source_geometry():
    first = web.create_browser_grid()
    second = web.create_browser_grid()
    assert first.crs == "EPSG:3857"
    assert (first.width, first.height) == (2544, 2482)
    assert first.pixel_size_x == pytest.approx(21.248104397509934)
    assert first.pixel_size_y == pytest.approx(21.248104397509934)
    assert first.transform == second.transform
    assert first.bounds == second.bounds
    assert (first.width, first.height) == (second.width, second.height)


def test_render_reserves_only_valid_all_white_and_preserves_partial_255_channels():
    reflectance = np.array(
        [
            [[0.22, 0.22, 0.22, 0.10]],
            [[0.22, 0.10, 0.22, 0.10]],
            [[0.22, 0.10, 0.22, 0.10]],
        ],
        dtype=np.float32,
    )
    valid = np.array([[True, True, False, True]])
    rendered, stats = web.render_browser_rgb(
        reflectance, valid, black_point=0.01, white_point=0.22, gamma=1.0
    )
    np.testing.assert_array_equal(rendered[:, 0, 0], [254, 254, 254])
    np.testing.assert_array_equal(rendered[:, 0, 1], [255, 109, 109])
    np.testing.assert_array_equal(rendered[:, 0, 2], [255, 255, 255])
    np.testing.assert_array_equal(rendered[:, 0, 3], [109, 109, 109])
    assert stats["all_white_before_adjustment_count"] == 1
    assert stats["remapped_pixel_count"] == 1
    assert stats["remapped_fraction_of_valid"] == pytest.approx(1 / 3)


def test_browser_cog_has_three_rgb_bands_explicit_nodata_and_cog_structure(tmp_path: Path):
    grid = _small_grid()
    rgb = np.full((3, grid.height, grid.width), 109, dtype=np.uint8)
    rgb[:, 0, 0] = web.NODATA_VALUE
    output = tmp_path / "rgb.tif"
    result = web.write_browser_cog(
        output,
        rgb,
        grid,
        black_point=0.01,
        white_point=0.22,
        gamma=1.0,
    )
    assert result["valid"] is True
    assert result["band_count"] == 3
    assert result["crs"] == "EPSG:3857"
    assert result["nodata"] == 255.0
    assert result["photometric_interpretation"] == "RGB"
    assert result["no_alpha_band"] is True
    assert result["overview_levels"] == web.expected_overview_levels(600, 600)
    with rasterio.open(output) as dataset:
        assert dataset.count == 3
        assert dataset.colorinterp == (
            rasterio.enums.ColorInterp.red,
            rasterio.enums.ColorInterp.green,
            rasterio.enums.ColorInterp.blue,
        )
        np.testing.assert_array_equal(dataset.read()[:, 0, 0], [255, 255, 255])


def test_paths_reject_canonical_and_non_delivery_roots(tmp_path: Path):
    with pytest.raises(ValueError, match="cannot target"):
        web._validate_paths(CONFIG, Path("data/derived/web-imagery"))
    with pytest.raises(ValueError, match="must be named"):
        web._validate_paths(CONFIG, tmp_path / "other")
    web._validate_paths(CONFIG, tmp_path / "web-delivery")


def test_manifest_is_ordered_and_uses_relative_paths(tmp_path: Path):
    grid = web.create_browser_grid()
    records = {}
    for year in (2020, 2017):
        records[str(year)] = {
            "year": year,
            "path": f"imagery/{year}/rgb.tif",
            "display": {"black": 0.01, "white": 0.22, "gamma": 1.0},
        }
        web._update_manifest(tmp_path / "imagery-manifest.json", grid, records[str(year)])
    payload = (tmp_path / "imagery-manifest.json").read_text(encoding="utf-8")
    assert '"2017"' in payload and payload.index('"2017"') < payload.index('"2020"')
    assert "/home/" not in payload
    assert payload.endswith("\n")


def test_cli_requires_one_explicit_supported_year():
    with pytest.raises(SystemExit):
        web.parse_args([])
    with pytest.raises(SystemExit):
        web.parse_args(["--all"])
    assert web.parse_args(["--year", "2017"]).year == 2017
    with pytest.raises(ValueError, match="unsupported year"):
        web.build(CONFIG, Path("data/derived/web-imagery"), Path("/tmp/web-delivery"), 2019)


def test_fixed_display_transform_is_explicitly_approved():
    values = np.full((3, 1, 1), 0.15, dtype=np.float32)
    rendered, _ = web.render_browser_rgb(
        values, np.ones((1, 1), dtype=bool), black_point=0.01, white_point=0.22, gamma=1.0
    )
    assert rendered[:, 0, 0].tolist() == [170, 170, 170]


def test_reprojection_does_not_modify_input_master(tmp_path: Path):
    source = tmp_path / "rgb-reflectance.tif"
    transform = from_origin(506260, 506300, 10, 10)
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=3,
        dtype="float32",
        crs="EPSG:32633",
        transform=transform,
        nodata=-9999.0,
    ) as dataset:
        dataset.write(np.full((3, 4, 4), 0.15, dtype=np.float32))
    before = source.read_bytes()
    grid = web.BrowserGrid(
        crs="EPSG:3857",
        transform=from_origin(1683000, 7000000, 20, 20),
        width=4,
        height=4,
        bounds=(1683000.0, 6999920.0, 1683080.0, 7000000.0),
        pixel_size_x=20.0,
        pixel_size_y=20.0,
    )
    web._reproject_reflectance(source, grid)
    assert source.read_bytes() == before


def test_identical_grid_and_overview_scheme_validate_for_all_years(tmp_path: Path):
    grid = _small_grid()
    paths = {}
    rgb = np.full((3, grid.height, grid.width), 109, dtype=np.uint8)
    for year in web.SUPPORTED_RGB_YEARS:
        path = tmp_path / str(year) / "rgb.tif"
        web.write_browser_cog(
            path,
            rgb,
            grid,
            black_point=0.01,
            white_point=0.22,
            gamma=1.0,
        )
        paths[year] = path
    result = web.validate_benchmark_alignment(paths, grid)
    assert result["identical_grid"] is True
    assert result["identical_overview_scheme"] is True
