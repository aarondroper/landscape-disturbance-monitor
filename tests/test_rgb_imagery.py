from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import landscape_monitor.build_rgb_imagery as rgb
import landscape_monitor.render_rgb as render
from landscape_monitor.composite_prototype import AnalysisGrid, ReflectanceTreatment, calculate_nbr
from landscape_monitor.config import load_config

CONFIG = Path(__file__).parents[1] / "config" / "project.toml"


def _small_grid(width: int = 600, height: int = 600) -> AnalysisGrid:
    return AnalysisGrid(
        crs="EPSG:32633",
        resolution=10.0,
        transform=from_origin(506260, 506260 + height * 10, 10, 10),
        width=width,
        height=height,
        bounds=(506260.0, 506260.0, 506260.0 + width * 10, 506260.0 + height * 10),
        aoi_mask=np.ones((height, width), dtype=bool),
    )


def test_visualization_grid_has_approved_bounds_dimensions_and_alignment():
    grid = rgb.create_visualization_grid(load_config(CONFIG))
    assert grid.crs == "EPSG:32633"
    assert grid.resolution == 10.0
    assert grid.bounds == rgb.VISUALIZATION_BOUNDS
    assert (grid.width, grid.height) == (2532, 2466)
    assert tuple(grid.transform) == (10.0, 0.0, 506260.0, 0.0, -10.0, 6883240.0, 0.0, 0.0, 1.0)


def test_configured_rgb_treatment_and_benchmark_years_are_final():
    config = load_config(CONFIG)
    assert config.rgb_black_point == 0.01
    assert config.rgb_white_point == 0.22
    assert config.rgb_gamma == 1.0
    assert config.benchmark_years == (2017, 2018, 2020, 2023, 2026)
    assert config.visualization_resolution_m == 10.0


def test_year_grids_are_identical():
    first = rgb.create_visualization_grid(load_config(CONFIG))
    second = rgb.create_visualization_grid(load_config(CONFIG))
    assert first.crs == second.crs
    assert first.bounds == second.bounds
    assert first.transform == second.transform
    assert (first.width, first.height) == (second.width, second.height)


def test_rgb_band_order_is_red_green_blue():
    assert rgb.rgb_band_order() == ("red", "green", "blue")


def test_source_nodata_and_scl_invalid_pixels_remain_invalid():
    values = np.array(
        [
            [[np.nan, 0.1], [0.1, 0.1]],
            [[0.1, 0.2], [0.1, 0.1]],
            [[0.1, 0.3], [0.1, 0.1]],
        ],
        dtype=np.float32,
    )
    scl = np.array([[4, 3], [4, 4]], dtype=np.uint8)
    prepared, valid = rgb.prepare_rgb_reflectance(values, scl, np.ones((2, 2), dtype=bool))
    assert valid.tolist() == [[False, False], [True, True]]
    assert np.isnan(prepared[:, 0, 0]).all()
    assert np.isnan(prepared[:, 0, 1]).all()


def test_negative_valid_rgb_reflectance_clamps_only_visualization_channel():
    values = np.array([[[-0.2]], [[0.1]], [[0.2]]], dtype=np.float32)
    prepared, valid = rgb.prepare_rgb_reflectance(
        values, np.array([[4]], dtype=np.uint8), np.ones((1, 1), dtype=bool)
    )
    assert valid[0, 0]
    np.testing.assert_allclose(prepared[:, 0, 0], [0.0, 0.1, 0.2])


def test_analytical_reject_behavior_remains_unchanged():
    values = calculate_nbr(
        np.array([[-0.1]], dtype=np.float32),
        np.array([[0.2]], dtype=np.float32),
        treatment=ReflectanceTreatment.REJECT,
    )
    assert np.isnan(values[0, 0])


def test_temporal_median_is_physical_and_channel_independent():
    first = np.array([[[0.01]], [[0.10]], [[0.20]]], dtype=np.float32)
    second = np.array([[[0.30]], [[0.20]], [[0.40]]], dtype=np.float32)
    median, count = rgb.exact_rgb_block_median([first, second])
    np.testing.assert_allclose(median[:, 0, 0], [0.155, 0.15, 0.30])
    np.testing.assert_array_equal(count[:, 0, 0], [2, 2, 2])
    rendered = rgb.fixed_display_transform(median)
    assert rendered[:, 0, 0].tolist() == [176, 170, 255]


def test_fixed_display_transform_has_fixed_clipping_and_no_year_argument():
    values = np.array([[[-1.0, 0.01, 0.155, 0.30, 1.0]]], dtype=np.float32)
    values = np.repeat(values, 3, axis=0)
    rendered = rgb.fixed_display_transform(values)
    assert rendered[0, 0].tolist() == [0, 0, 176, 255, 255]
    assert "year" not in rgb.fixed_display_transform.__code__.co_varnames


def test_alpha_creation_is_opaque_or_transparent():
    np.testing.assert_array_equal(
        rgb.create_alpha(np.array([[True, False]], dtype=bool)),
        np.array([[255, 0]], dtype=np.uint8),
    )


def test_cli_requires_explicit_year_and_has_no_implicit_all_mode():
    with pytest.raises(SystemExit):
        rgb.parse_args([])
    with pytest.raises(SystemExit):
        rgb.parse_args(["--all"])
    assert rgb.parse_args(["--year", "2017"]).year == 2017


def test_unsupported_year_fails_clearly():
    with pytest.raises(ValueError, match="unsupported year"):
        rgb._build_interval(load_config(CONFIG), 2019)


def test_rgb_output_cannot_target_canonical_analytical_paths(tmp_path: Path):
    with pytest.raises(ValueError, match="canonical analytical"):
        rgb._validate_output_root(Path("data/derived/annual"), CONFIG)
    rgb._validate_output_root(tmp_path / "web-imagery", CONFIG)


def test_native_gdal_cog_is_written_and_validated(tmp_path: Path):
    grid = _small_grid()
    master = tmp_path / "rgb-reflectance.tif"
    with rasterio.open(master, "w", **rgb._rgb_profile(grid)) as dataset:
        values = np.full((3, grid.height, grid.width), 0.15, dtype=np.float32)
        dataset.write(values)
    output = tmp_path / "rgb-web.tif"
    metadata = rgb._write_web_cog(master, output, grid, load_config(CONFIG), rgb.MemoryTelemetry())
    assert metadata["valid"] is True
    assert metadata["layout"] == "COG"
    assert metadata["compression"] == "DEFLATE"
    assert metadata["block_size"] == [256, 256]
    assert metadata["overview_levels"]
    with rasterio.open(output) as dataset:
        assert dataset.count == 4
        assert dataset.colorinterp[-1].name == "alpha"
        np.testing.assert_array_equal(dataset.read(4, window=((0, 1), (0, 1))), [[255]])


def test_local_renderer_uses_explicit_white_point_and_default_remains_configured():
    config = load_config(CONFIG)
    assert render.display_parameters(config) == {
        "black_point": 0.01,
        "white_point": 0.22,
        "gamma": 1.0,
    }
    assert render.display_parameters(config, 0.22)["white_point"] == 0.22
    assert load_config(CONFIG).rgb_white_point == 0.22


def test_local_renderer_does_not_use_remote_reader(monkeypatch, tmp_path: Path):
    grid = _small_grid(32, 32)
    master = tmp_path / "rgb-reflectance.tif"
    with rasterio.open(master, "w", **rgb._rgb_profile(grid)) as dataset:
        dataset.write(np.full((3, grid.height, grid.width), 0.15, dtype=np.float32))

    def fail_remote(*args, **kwargs):
        raise AssertionError("remote reader must not be called")

    monkeypatch.setattr(rgb, "read_remote_asset_to_grid", fail_remote)
    output = tmp_path / "rgb-web-w022.tif"
    result = render.render_master_to_cog(
        master,
        output,
        grid,
        black_point=0.01,
        white_point=0.22,
        gamma=1.0,
    )
    assert result["valid"] is True


def test_candidate_cannot_overwrite_canonical_products(tmp_path: Path):
    grid = _small_grid(32, 32)
    master = tmp_path / "rgb-reflectance.tif"
    with rasterio.open(master, "w", **rgb._rgb_profile(grid)) as dataset:
        dataset.write(np.full((3, grid.height, grid.width), 0.15, dtype=np.float32))
    for name in ("rgb-web.tif", "rgb-reflectance.tif"):
        with pytest.raises(ValueError, match="canonical"):
            render.render_master_to_cog(
                master,
                tmp_path / name,
                grid,
                black_point=0.01,
                white_point=0.22,
                gamma=1.0,
            )


def test_candidate_cog_preserves_grid_and_alpha_mask(tmp_path: Path):
    grid = _small_grid(32, 32)
    master = tmp_path / "rgb-reflectance.tif"
    values = np.full((3, grid.height, grid.width), 0.15, dtype=np.float32)
    values[:, 0, 0] = rgb.FLOAT_NODATA
    with rasterio.open(master, "w", **rgb._rgb_profile(grid)) as dataset:
        dataset.write(values)
    output = tmp_path / "rgb-web-w022.tif"
    render.render_master_to_cog(
        master,
        output,
        grid,
        black_point=0.01,
        white_point=0.22,
        gamma=1.0,
    )
    with rasterio.open(output) as dataset:
        rgb.validate_visualization_grid(dataset, grid)
        assert dataset.count == 4
        assert dataset.read(4)[0, 0] == 0
        assert dataset.read(4)[1, 1] == 255


def test_canonical_local_renderer_uses_configured_transform(tmp_path: Path):
    grid = _small_grid(32, 32)
    master = tmp_path / "rgb-reflectance.tif"
    with rasterio.open(master, "w", **rgb._rgb_profile(grid)) as dataset:
        dataset.write(np.full((3, grid.height, grid.width), 0.15, dtype=np.float32))
    output = tmp_path / "rgb-web.tif"
    metadata = render.render_master_to_canonical_cog(
        master,
        output,
        grid,
        **render.display_parameters(load_config(CONFIG)),
    )
    assert metadata["white_point"] == 0.22
    with rasterio.open(output) as dataset:
        assert dataset.read(1, window=((0, 1), (0, 1))).item() == 170


def test_all_benchmark_cog_alignment_validation(tmp_path: Path):
    grid = _small_grid(32, 32)
    source = tmp_path / "source.tif"
    with rasterio.open(source, "w", **rgb._rgb_profile(grid)) as dataset:
        dataset.write(np.full((3, grid.height, grid.width), 0.15, dtype=np.float32))
    paths = {}
    for year in rgb.SUPPORTED_RGB_YEARS:
        output = tmp_path / str(year) / "rgb-web-candidate.tif"
        output.parent.mkdir()
        render.render_master_to_cog(
            source,
            output,
            grid,
            black_point=0.01,
            white_point=0.22,
            gamma=1.0,
        )
        paths[year] = output
    result = rgb.validate_benchmark_alignment(paths, grid)
    assert result["valid"] is True
    assert result["identical_grid"] is True
    assert result["identical_overview_scheme"] is True


def test_clipping_statistics_are_deterministic_and_channel_specific():
    values = np.array(
        [
            [[0.00, 0.01], [0.22, 0.30]],
            [[0.01, 0.02], [0.22, 0.30]],
            [[0.01, 0.03], [0.22, 0.30]],
        ],
        dtype=np.float32,
    )
    result = render.calculate_tonal_statistics(
        values, black_point=0.01, white_point=0.22, gamma=1.0
    )
    assert result["valid_pixel_count"] == 4
    assert result["channels"]["red"]["fraction_source_le_black"] == pytest.approx(0.5)
    assert result["channels"]["red"]["fraction_source_ge_white"] == pytest.approx(0.5)
    assert result["fraction_any_channel_clips_high"] == pytest.approx(0.5)
    assert result["fraction_all_channels_clip_high"] == pytest.approx(0.5)
    assert result["fraction_any_channel_clips_low"] == pytest.approx(0.5)
    assert result["fraction_all_channels_clip_low"] == pytest.approx(0.25)


def test_candidate_transform_is_identical_for_all_channels_and_years():
    values = np.array([[[0.10]], [[0.10]], [[0.10]]], dtype=np.float32)
    first = render.calculate_tonal_statistics(
        values, black_point=0.01, white_point=0.22, gamma=1.0
    )
    second = render.calculate_tonal_statistics(
        values, black_point=0.01, white_point=0.22, gamma=1.0
    )
    assert first == second
    assert (
        len({first["channels"][name]["rendered_median"] for name in ("red", "green", "blue")})
        == 1
    )


def test_local_render_does_not_change_reflectance_master(tmp_path: Path):
    import hashlib

    grid = _small_grid(32, 32)
    master = tmp_path / "rgb-reflectance.tif"
    with rasterio.open(master, "w", **rgb._rgb_profile(grid)) as dataset:
        dataset.write(np.full((3, grid.height, grid.width), 0.15, dtype=np.float32))
    before = hashlib.sha256(master.read_bytes()).digest()
    render.render_master_to_cog(
        master,
        tmp_path / "rgb-web-w022.tif",
        grid,
        black_point=0.01,
        white_point=0.22,
        gamma=1.0,
    )
    assert hashlib.sha256(master.read_bytes()).digest() == before
