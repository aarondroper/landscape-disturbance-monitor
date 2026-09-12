"""Build one explicit-year, browser-oriented Sentinel-2 RGB composite.

RGB presentation imagery is deliberately separate from the 20 m analytical
NBR/NDVI pipeline.  Each August acquisition date is processed sequentially,
written as a temporary AOI-only reflectance raster, and reduced block by block
to an exact physical-reflectance median before one fixed display transform is
applied.  No full Sentinel scene or full-AOI temporal stack is retained.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import tempfile
import time
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np
import rasterio
from matplotlib import pyplot as plt
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import from_origin
from rasterio.windows import Window

from .build_composite_prototype import _asset, load_inventory
from .composite_prototype import (
    ANALYSIS_CRS,
    FLOAT_NODATA,
    SCL_INVALID_CLASSES,
    AnalysisGrid,
    group_acquisition_items,
    read_asset_metadata,
    read_remote_asset_to_grid,
    valid_scl_mask,
)
from .config import ProjectConfig, load_config

RGB_BANDS = ("red", "green", "blue")
SUPPORTED_RGB_YEARS = (2017, 2018, 2020, 2023, 2026)
RGB_BLACK_POINT = 0.01
RGB_WHITE_POINT = 0.22
RGB_GAMMA = 1.0
VISUALIZATION_BOUNDS = (506260.0, 6858580.0, 531580.0, 6883240.0)
VISUALIZATION_WIDTH = 2532
VISUALIZATION_HEIGHT = 2466
RGB_BLOCK_SIZE = 256
RGB_TEMP_PREFIX = "rgb-reflectance"


@dataclass(frozen=True)
class TemporaryRGBAcquisition:
    date: str
    path: Path


def _linux_peak_rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / 1024.0 if value < 10_000_000 else value / (1024.0 * 1024.0)


class MemoryTelemetry:
    """Native-process peak-RSS and stage telemetry."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, stage: str) -> dict[str, Any]:
        event = {"stage": stage, "max_rss_mib": round(_linux_peak_rss_mib(), 2)}
        self.events.append(event)
        print(f"memory {stage}: max_rss={event['max_rss_mib']:.2f} MiB", flush=True)
        return event

    @property
    def peak_mib(self) -> float:
        return max((float(event["max_rss_mib"]) for event in self.events), default=0.0)


def _directory_size(path: Path) -> int:
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def create_visualization_grid(config: ProjectConfig) -> AnalysisGrid:
    """Return the fixed, AOI-masked 10 m presentation grid."""
    resolution = float(config.visualization_resolution_m)
    if resolution != 10.0:
        raise ValueError("RGB imagery requires visualization.resolution_m = 10")
    left, bottom, right, top = VISUALIZATION_BOUNDS
    width = int(round((right - left) / resolution))
    height = int(round((top - bottom) / resolution))
    if (width, height) != (VISUALIZATION_WIDTH, VISUALIZATION_HEIGHT):
        raise ValueError("approved visualization bounds do not produce the expected dimensions")
    transform = from_origin(left, top, resolution, resolution)

    from rasterio.features import geometry_mask
    from rasterio.warp import transform as transform_coordinates

    xs, ys = transform_coordinates(
        "EPSG:4326",
        ANALYSIS_CRS,
        [config.aoi.west, config.aoi.east, config.aoi.east, config.aoi.west, config.aoi.west],
        [config.aoi.south, config.aoi.south, config.aoi.north, config.aoi.north, config.aoi.south],
    )
    geometry = {"type": "Polygon", "coordinates": [[[x, y] for x, y in zip(xs, ys, strict=True)]]}
    aoi_mask = geometry_mask(
        [geometry], out_shape=(height, width), transform=transform, invert=True
    )
    return AnalysisGrid(
        crs=ANALYSIS_CRS,
        resolution=resolution,
        transform=transform,
        width=width,
        height=height,
        bounds=VISUALIZATION_BOUNDS,
        aoi_mask=aoi_mask,
    )


def validate_visualization_grid(dataset: rasterio.DatasetReader, grid: AnalysisGrid) -> None:
    """Ensure a presentation raster is pixel-aligned to the approved grid."""
    if str(dataset.crs) != grid.crs:
        raise ValueError(f"unexpected CRS {dataset.crs}; expected {grid.crs}")
    if (dataset.width, dataset.height) != (grid.width, grid.height):
        raise ValueError("presentation raster dimensions do not match the approved grid")
    if not np.allclose(tuple(dataset.transform), tuple(grid.transform), atol=1e-9):
        raise ValueError("presentation raster transform does not match the approved grid")
    if not np.allclose(tuple(dataset.bounds), grid.bounds, atol=1e-6):
        raise ValueError("presentation raster bounds do not match the approved grid")


def rgb_band_order() -> tuple[str, str, str]:
    """Return natural-color output order, kept explicit for tests and metadata."""
    return RGB_BANDS


def rgb_quality_mask(
    rgb_reflectance: np.ndarray, scl: np.ndarray, aoi_mask: np.ndarray
) -> np.ndarray:
    """Return pixels valid in all RGB channels, SCL, and the project AOI."""
    rgb = np.asarray(rgb_reflectance, dtype=np.float32)
    if rgb.ndim != 3 or rgb.shape[0] != 3:
        raise ValueError("rgb_reflectance must have shape (3, rows, columns)")
    return np.all(np.isfinite(rgb), axis=0) & valid_scl_mask(scl) & np.asarray(aoi_mask, dtype=bool)


def prepare_rgb_reflectance(
    rgb_reflectance: np.ndarray, scl: np.ndarray, aoi_mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Clamp valid negative display reflectance and apply the unchanged SCL rule."""
    rgb = np.asarray(rgb_reflectance, dtype=np.float32).copy()
    valid = rgb_quality_mask(rgb, scl, aoi_mask)
    rgb[:, np.isfinite(rgb).all(axis=0)] = np.maximum(
        rgb[:, np.isfinite(rgb).all(axis=0)], 0.0
    )
    rgb[:, ~valid] = np.nan
    return rgb, valid


def exact_rgb_block_median(observations: Sequence[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Return exact per-channel physical-reflectance median and valid count."""
    if not observations:
        raise ValueError("at least one RGB observation is required")
    stack = np.stack([np.asarray(value, dtype=np.float32) for value in observations])
    if stack.ndim != 4 or stack.shape[1] != 3:
        raise ValueError("RGB observations must have shape (3, rows, columns)")
    valid_count = np.sum(np.isfinite(stack), axis=0, dtype=np.uint16)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        median = np.nanmedian(stack, axis=0).astype(np.float32, copy=False)
    median[valid_count == 0] = np.nan
    return median, valid_count


def fixed_display_transform(
    rgb_reflectance: np.ndarray,
    *,
    black_point: float = RGB_BLACK_POINT,
    white_point: float = RGB_WHITE_POINT,
    gamma: float = RGB_GAMMA,
) -> np.ndarray:
    """Render physical RGB reflectance using one fixed transform for all years."""
    if not 0 <= black_point < white_point or gamma <= 0:
        raise ValueError("display points must be ordered and gamma must be positive")
    rgb = np.asarray(rgb_reflectance, dtype=np.float32)
    if rgb.ndim != 3 or rgb.shape[0] != 3:
        raise ValueError("rgb_reflectance must have shape (3, rows, columns)")
    finite = np.isfinite(rgb)
    values = np.where(finite, np.maximum(rgb, 0.0), black_point)
    normalized = np.clip((values - black_point) / (white_point - black_point), 0.0, 1.0)
    rendered = np.power(normalized, 1.0 / gamma) * 255.0
    return np.rint(rendered).astype(np.uint8)


def create_alpha(valid_mask: np.ndarray) -> np.ndarray:
    """Return an opaque/transparent alpha channel without using black as nodata."""
    return np.where(np.asarray(valid_mask, dtype=bool), 255, 0).astype(np.uint8)


def _windows(grid: AnalysisGrid, block_size: int = RGB_BLOCK_SIZE) -> Iterator[Window]:
    for row_off in range(0, grid.height, block_size):
        for col_off in range(0, grid.width, block_size):
            yield Window(
                col_off,
                row_off,
                min(block_size, grid.width - col_off),
                min(block_size, grid.height - row_off),
            )


def _rgb_profile(grid: AnalysisGrid) -> dict[str, Any]:
    return {
        "driver": "GTiff",
        "height": grid.height,
        "width": grid.width,
        "count": 3,
        "dtype": "float32",
        "crs": grid.crs,
        "transform": grid.transform,
        "nodata": FLOAT_NODATA,
        "tiled": True,
        "blockxsize": RGB_BLOCK_SIZE,
        "blockysize": RGB_BLOCK_SIZE,
        "compress": "deflate",
        "predictor": 3,
        "BIGTIFF": "IF_SAFER",
    }


def _item_date(item: dict[str, Any]) -> date:
    value = item.get("datetime")
    if not value:
        raise ValueError(f"Item {item.get('id')} has no datetime")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _build_interval(config: ProjectConfig, year: int) -> tuple[date, date]:
    if year not in SUPPORTED_RGB_YEARS or year not in config.benchmark_years:
        raise ValueError(
            f"unsupported year {year}; RGB benchmark years are {config.benchmark_years}"
        )
    if (config.month, config.window_start_day, config.window_end_day) != (8, 1, 31):
        raise ValueError("RGB imagery requires the configured interval August 1 through August 31")
    return date(year, 8, 1), date(year, 8, 31)


def _processable(item: dict[str, Any]) -> bool:
    return all(
        any(
            asset.get("cog_likely") and str(asset.get("href", "")).startswith("https://")
            for asset in item.get("relevant_assets", {}).get(band, [])
        )
        for band in (*RGB_BANDS, "scl")
    )


def _selected_asset(item: dict[str, Any], band: str) -> dict[str, Any]:
    return _asset(item, band)


def _scale_offset_summary(
    items: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, float | None]]]:
    result: dict[str, list[dict[str, float | None]]] = {}
    for band in (*RGB_BANDS, "scl"):
        pairs = {
            (
                read_asset_metadata(_selected_asset(item, band))["scale"],
                read_asset_metadata(_selected_asset(item, band))["offset"],
            )
            for item in items
            if item.get("relevant_assets", {}).get(band)
        }
        result[band] = [
            {"scale": scale, "offset": offset} for scale, offset in sorted(pairs, key=str)
        ]
    return result


def _mosaic_rgb_into(
    destination: np.ndarray, filled: np.ndarray, values: np.ndarray, valid: np.ndarray
) -> None:
    select = np.asarray(valid, dtype=bool) & ~filled
    destination[:, select] = np.asarray(values, dtype=np.float32)[:, select]
    filled[select] = True


def _process_acquisition(
    acquisition_date: str,
    items: list[dict[str, Any]],
    grid: AnalysisGrid,
    workspace: Path,
    telemetry: MemoryTelemetry,
) -> tuple[TemporaryRGBAcquisition | None, dict[str, Any]]:
    """Read one date's tiles in deterministic order and write one RGB raster."""
    print(f"{acquisition_date}: reading {len(items)} item(s)", flush=True)
    date_rgb = np.full((3, *grid.shape), np.nan, dtype=np.float32)
    filled = np.zeros(grid.shape, dtype=bool)
    aoi_pixels = int(np.count_nonzero(grid.aoi_mask))

    for item in items:
        reflectance = np.empty((3, *grid.shape), dtype=np.float32)
        for index, band in enumerate(RGB_BANDS):
            reflectance[index] = read_remote_asset_to_grid(
                _selected_asset(item, band),
                grid,
                **read_asset_metadata(_selected_asset(item, band)),
                resampling=Resampling.average,
            )
        scl = read_remote_asset_to_grid(
            _selected_asset(item, "scl"),
            grid,
            scale=1.0,
            offset=0.0,
            resampling=Resampling.nearest,
        )
        scl = np.where(np.isfinite(scl), np.rint(scl), 0).astype(np.uint8)
        prepared, valid = prepare_rgb_reflectance(reflectance, scl, grid.aoi_mask)
        _mosaic_rgb_into(date_rgb, filled, prepared, valid)
        del reflectance, scl, prepared, valid

    valid_pixel_count = int(np.count_nonzero(filled & grid.aoi_mask))
    record: dict[str, Any] = {
        "date": acquisition_date,
        "item_ids": [item["id"] for item in items],
        "acquisition_datetimes": [item.get("datetime") for item in items],
        "mgrs_tiles": sorted({str(item.get("mgrs_tile")) for item in items}),
        "scene_cloud_cover": [item.get("eo:cloud_cover") for item in items],
        "valid_pixel_count": valid_pixel_count,
        "valid_pixel_percentage": 100.0 * valid_pixel_count / aoi_pixels if aoi_pixels else 0.0,
        "mosaic_rule": "first valid RGB pixel in (MGRS tile, Item ID) order; no averaging",
    }
    if valid_pixel_count == 0:
        del date_rgb, filled
        telemetry.record(f"after acquisition {acquisition_date} (no valid pixels)")
        return None, record

    index = len(list(workspace.glob(f"*_{RGB_TEMP_PREFIX}.tif")))
    safe_date = acquisition_date.replace("-", "")
    path = workspace / f"{index:03d}_{safe_date}_{RGB_TEMP_PREFIX}.tif"
    output = np.where(np.isfinite(date_rgb), date_rgb, FLOAT_NODATA).astype(np.float32)
    with rasterio.open(path, "w", **_rgb_profile(grid)) as dataset:
        dataset.write(output)
    del date_rgb, filled, output
    telemetry.record(f"after acquisition {acquisition_date}")
    return TemporaryRGBAcquisition(acquisition_date, path), record


def _write_reflectance_master(
    acquisitions: Sequence[TemporaryRGBAcquisition],
    grid: AnalysisGrid,
    output_path: Path,
    telemetry: MemoryTelemetry,
) -> dict[str, Any]:
    """Reduce date rasters to an exact, channel-independent physical median."""
    if not acquisitions:
        raise ValueError("cannot reduce a year with no usable RGB acquisition rasters")
    datasets = [rasterio.open(acquisition.path) for acquisition in acquisitions]
    block_count = 0
    valid_pixel_count = 0
    try:
        with rasterio.open(output_path, "w", **_rgb_profile(grid)) as output:
            for window in _windows(grid):
                row, col = int(window.row_off), int(window.col_off)
                height, width = int(window.height), int(window.width)
                rgb_blocks: list[np.ndarray] = []
                for dataset in datasets:
                    values = dataset.read(window=window).astype(np.float32, copy=False)
                    values[values == FLOAT_NODATA] = np.nan
                    values[~np.isfinite(values)] = np.nan
                    rgb_blocks.append(values)
                median, channel_counts = exact_rgb_block_median(rgb_blocks)
                valid = np.all(np.isfinite(median), axis=0) & grid.aoi_mask[
                    row : row + height, col : col + width
                ]
                valid_pixel_count += int(np.count_nonzero(valid))
                output.write(
                    np.where(np.isfinite(median), median, FLOAT_NODATA).astype(np.float32),
                    window=window,
                )
                del rgb_blocks, median, channel_counts, valid
                block_count += 1
                if block_count == 1 or block_count % 32 == 0:
                    telemetry.record(f"during RGB block reduction {block_count}")
    finally:
        for dataset in datasets:
            dataset.close()
    telemetry.record("after RGB reflectance reduction")
    return {
        "block_count": block_count,
        "block_size": [RGB_BLOCK_SIZE, RGB_BLOCK_SIZE],
        "valid_pixel_count": valid_pixel_count,
    }


def _read_master_block(dataset: rasterio.DatasetReader, window: Window) -> np.ndarray:
    values = dataset.read(window=window).astype(np.float32, copy=False)
    values[values == FLOAT_NODATA] = np.nan
    values[~np.isfinite(values)] = np.nan
    return values


def _write_web_cog(
    master_path: Path,
    output_path: Path,
    grid: AnalysisGrid,
    config: ProjectConfig,
    telemetry: MemoryTelemetry,
) -> dict[str, Any]:
    """Render a reflectance master into a GDAL-native RGBA Cloud Optimized GeoTIFF."""
    with rasterio.open(master_path) as master, rasterio.open(
        output_path,
        "w",
        driver="COG",
        height=grid.height,
        width=grid.width,
        count=4,
        dtype="uint8",
        crs=grid.crs,
        transform=grid.transform,
        compress="DEFLATE",
        level=6,
        blocksize=RGB_BLOCK_SIZE,
        overview_resampling="average",
        BIGTIFF="IF_SAFER",
    ) as output:
        output.colorinterp = (
            ColorInterp.red,
            ColorInterp.green,
            ColorInterp.blue,
            ColorInterp.alpha,
        )
        for window in _windows(grid):
            values = _read_master_block(master, window)
            valid = np.all(np.isfinite(values), axis=0)
            rendered = fixed_display_transform(
                values,
                black_point=config.rgb_black_point,
                white_point=config.rgb_white_point,
                gamma=config.rgb_gamma,
            )
            rgba = np.concatenate((rendered, create_alpha(valid)[None, ...]), axis=0)
            output.write(rgba, window=window)
            del values, rendered, rgba, valid
    telemetry.record("after web COG render")
    return validate_cog(output_path, grid)


def validate_cog(path: Path, grid: AnalysisGrid) -> dict[str, Any]:
    """Validate native GDAL COG metadata, tiling, overviews, and RGBA semantics."""
    with rasterio.open(path) as dataset:
        validate_visualization_grid(dataset, grid)
        structure = dataset.tags(ns="IMAGE_STRUCTURE")
        overviews = dataset.overviews(1)
        overview_sets = [dataset.overviews(index) for index in range(1, dataset.count + 1)]
        alpha = dataset.read(4)
        result = {
            "valid": (
                dataset.driver == "GTiff"
                and structure.get("LAYOUT") == "COG"
                and bool(dataset.profile.get("tiled"))
                and dataset.count == 4
                and dataset.dtypes == ("uint8",) * 4
                and all(values == overviews for values in overview_sets)
                and (bool(overviews) if max(dataset.width, dataset.height) > 512 else True)
                and set(np.unique(alpha)).issubset({0, 255})
            ),
            "validation_method": (
                "GDAL native COG driver LAYOUT metadata plus Rasterio structural readback"
            ),
            "driver": dataset.driver,
            "layout": structure.get("LAYOUT"),
            "crs": str(dataset.crs),
            "width": dataset.width,
            "height": dataset.height,
            "bounds": list(dataset.bounds),
            "transform": list(dataset.transform),
            "compression": structure.get("COMPRESSION", str(dataset.compression).upper()),
            "block_size": [dataset.block_shapes[0][1], dataset.block_shapes[0][0]],
            "overview_levels": overviews,
            "overview_resampling": structure.get("OVERVIEW_RESAMPLING"),
            "band_count": dataset.count,
            "dtypes": list(dataset.dtypes),
            "color_interpretation": [value.name for value in dataset.colorinterp],
            "mask_flags": [[flag.name for flag in flags] for flags in dataset.mask_flag_enums],
            "nodata": dataset.nodata,
            "alpha_values_sampled": sorted(int(value) for value in np.unique(alpha)),
            "file_size_bytes": path.stat().st_size,
        }
    if not result["valid"]:
        raise ValueError(f"COG validation failed for {path}: {result}")
    return result


def validate_benchmark_alignment(
    paths: dict[int, Path], grid: AnalysisGrid
) -> dict[str, Any]:
    """Validate every benchmark COG and fail on any grid or overview mismatch."""
    if tuple(sorted(paths)) != SUPPORTED_RGB_YEARS:
        raise ValueError(f"expected exactly benchmark years {SUPPORTED_RGB_YEARS}")
    metadata = {year: validate_cog(path, grid) for year, path in sorted(paths.items())}
    reference = metadata[SUPPORTED_RGB_YEARS[0]]
    for year in SUPPORTED_RGB_YEARS[1:]:
        candidate = metadata[year]
        for key in ("crs", "width", "height", "bounds", "transform", "block_size"):
            if candidate[key] != reference[key]:
                raise ValueError(
                    f"benchmark COG alignment mismatch for {year}: {key} differs from "
                    f"{SUPPORTED_RGB_YEARS[0]}"
                )
        if candidate["overview_levels"] != reference["overview_levels"]:
            raise ValueError(
                f"benchmark COG overview mismatch for {year}: overview scheme differs"
            )
    return {
        "valid": True,
        "years": list(SUPPORTED_RGB_YEARS),
        "identical_grid": True,
        "identical_overview_scheme": True,
        "cogs": {str(year): metadata[year] for year in SUPPORTED_RGB_YEARS},
    }


def _quicklook_array(path: Path, max_dimension: int = 1200) -> np.ndarray:
    with rasterio.open(path) as dataset:
        scale = min(1.0, max_dimension / max(dataset.width, dataset.height))
        height = max(1, int(round(dataset.height * scale)))
        width = max(1, int(round(dataset.width * scale)))
        return dataset.read(
            out_shape=(4, height, width), resampling=Resampling.nearest
        )


def _save_quicklook(path: Path, rgba: np.ndarray, title: str) -> None:
    figure, axis = plt.subplots(figsize=(9, 7), constrained_layout=True)
    try:
        axis.imshow(
            np.moveaxis(rgba[:3], 0, -1),
            origin="upper",
            alpha=rgba[3] / 255.0,
            extent=VISUALIZATION_BOUNDS,
        )
        axis.set_title(title)
        axis.set_xlabel("Easting (m), EPSG:32633")
        axis.set_ylabel("Northing (m), EPSG:32633")
        axis.set_aspect("equal")
        figure.savefig(path, dpi=120)
    finally:
        plt.close(figure)


def _save_comparison(output_root: Path) -> Path | None:
    paths = {
        year: output_root / str(year) / "rgb-web.tif" for year in SUPPORTED_RGB_YEARS
    }
    if not all(path.exists() for path in paths.values()):
        return None
    arrays = {year: _quicklook_array(path) for year, path in paths.items()}
    if len({array.shape for array in arrays.values()}) != 1:
        raise ValueError("comparison quicklooks do not have identical shapes")
    path = output_root / "rgb-benchmark-comparison.png"
    figure, axes = plt.subplots(2, 3, figsize=(18, 12), constrained_layout=True)
    try:
        comparison_axes = axes.flat[: len(SUPPORTED_RGB_YEARS)]
        for axis, year in zip(comparison_axes, SUPPORTED_RGB_YEARS, strict=True):
            rgba = arrays[year]
            axis.imshow(
                np.moveaxis(rgba[:3], 0, -1),
                origin="upper",
                alpha=rgba[3] / 255.0,
                extent=VISUALIZATION_BOUNDS,
            )
            axis.set_title(str(year))
            axis.set_xlabel("Easting (m)")
            axis.set_ylabel("Northing (m)")
            axis.set_aspect("equal")
        axes.flat[-1].set_visible(False)
        figure.savefig(path, dpi=120)
    finally:
        plt.close(figure)
    return path


def _validate_output_root(output_root: Path, config_path: Path) -> None:
    repo_root = config_path.resolve().parents[1]
    candidate = output_root.resolve()
    canonical_roots = [
        repo_root / "data" / "derived" / name
        for name in ("annual", "prototype", "disturbance", "recovery")
    ]
    if any(candidate == root or root in candidate.parents for root in canonical_roots):
        raise ValueError("RGB output root cannot be a canonical analytical output path")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _merge_summary(path: Path, year_summary: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    else:
        previous = {}
    years = dict(previous.get("years", {}))
    years[str(year_summary["year"])] = year_summary["year_record"]
    merged = {key: value for key, value in previous.items() if key != "years"}
    merged.update(
        {
            "product": "benchmark browser-oriented natural-color Sentinel-2 imagery",
            "benchmark_years": list(SUPPORTED_RGB_YEARS),
            "years": {key: years[key] for key in sorted(years)},
            "aoi": year_summary["aoi"],
            "visualization_grid": year_summary["visualization_grid"],
            "source": year_summary["source"],
            "processing": year_summary["processing"],
            "outputs": year_summary["outputs"],
        }
    )
    _write_json(path, merged)
    return merged


def build(
    config_path: Path,
    inventory_path: Path,
    output_root: Path,
    temp_root: Path,
    year: int,
) -> dict[str, Any]:
    """Build exactly one explicit RGB benchmark year."""
    _validate_output_root(output_root, config_path)
    started = time.perf_counter()
    telemetry = MemoryTelemetry()
    config = load_config(config_path)
    start_date, end_date = _build_interval(config, year)
    grid = create_visualization_grid(config)
    inventory = load_inventory(inventory_path)
    selected = sorted(
        [
            item
            for item in inventory
            if item.get("year") == year and start_date <= _item_date(item) <= end_date
        ],
        key=lambda item: (str(item.get("datetime") or ""), str(item["id"])),
    )
    groups = group_acquisition_items(selected)
    processable_by_date = {
        key: [item for item in values if _processable(item)] for key, values in groups.items()
    }
    print(
        f"{year}: {len(selected)} STAC items in {len(groups)} acquisition groups; "
        "processing sequentially",
        flush=True,
    )
    telemetry.record("after STAC discovery/grouping")

    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = output_root / str(year)
    output_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".rgb-{year}-staging-", dir=output_root))
    temp_root.mkdir(parents=True, exist_ok=True)
    peak_temp_bytes = 0
    acquisition_records: list[dict[str, Any]] = []
    acquisitions: list[TemporaryRGBAcquisition] = []
    last_date: str | None = None
    try:
        with rasterio.Env(
            GDAL_CACHEMAX=256,
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_USE_HEAD="NO",
            GDAL_HTTP_TIMEOUT="60",
            GDAL_HTTP_MAX_RETRY="2",
            GDAL_HTTP_RETRY_DELAY="1",
        ):
            year_temp_root = temp_root / str(year)
            year_temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=f"{year}-", dir=year_temp_root) as temp_name:
                workspace = Path(temp_name)
                for acquisition_date in sorted(groups):
                    last_date = acquisition_date
                    if not processable_by_date[acquisition_date]:
                        items = groups[acquisition_date]
                        record = {
                            "date": acquisition_date,
                            "item_ids": [item["id"] for item in items],
                            "acquisition_datetimes": [item.get("datetime") for item in items],
                            "mgrs_tiles": sorted({str(item.get("mgrs_tile")) for item in items}),
                            "scene_cloud_cover": [item.get("eo:cloud_cover") for item in items],
                            "valid_pixel_count": 0,
                            "valid_pixel_percentage": 0.0,
                            "mosaic_rule": "no processable HTTPS COG item",
                        }
                        acquisition_records.append(record)
                        continue
                    acquisition, record = _process_acquisition(
                        acquisition_date,
                        processable_by_date[acquisition_date],
                        grid,
                        workspace,
                        telemetry,
                    )
                    acquisition_records.append(record)
                    if acquisition is not None:
                        acquisitions.append(acquisition)
                        peak_temp_bytes = max(peak_temp_bytes, _directory_size(workspace))
                telemetry.record("before RGB block reduction")
                reduction = _write_reflectance_master(
                    acquisitions, grid, staging_dir / "rgb-reflectance.tif", telemetry
                )
                peak_temp_bytes = max(peak_temp_bytes, _directory_size(workspace))
        web_metadata = _write_web_cog(
            staging_dir / "rgb-reflectance.tif",
            staging_dir / "rgb-web.tif",
            grid,
            config,
            telemetry,
        )
        quicklook = _quicklook_array(staging_dir / "rgb-web.tif")
        _save_quicklook(staging_dir / "rgb-quicklook.png", quicklook, f"{year} August RGB median")
        telemetry.record("after quicklook")

        # Tonal diagnostics are computed from the local master after the
        # memory-bounded build stages and never affect the generated pixels.
        from .render_rgb import _master_array, calculate_tonal_statistics

        tonal_statistics = calculate_tonal_statistics(
            _master_array(staging_dir / "rgb-reflectance.tif"),
            black_point=config.rgb_black_point,
            white_point=config.rgb_white_point,
            gamma=config.rgb_gamma,
        )
        telemetry.record("build end")

        aoi_pixels = int(np.count_nonzero(grid.aoi_mask))
        usable_records = [
            record for record in acquisition_records if record["valid_pixel_count"] > 0
        ]
        master_valid = int(reduction["valid_pixel_count"])
        elapsed = round(time.perf_counter() - started, 3)
        year_record: dict[str, Any] = {
            "year": year,
            "requested_interval": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "stac_item_count": len(selected),
            "grouped_acquisition_count": len(groups),
            "usable_acquisition_count": len(usable_records),
            "processable_item_count": sum(len(values) for values in processable_by_date.values()),
            "item_ids": [item["id"] for item in selected],
            "mgrs_tiles": sorted({str(item.get("mgrs_tile")) for item in selected}),
            "acquisition_groups": acquisition_records,
            "valid_coverage": {
                "rgb_percent": 100.0 * master_valid / aoi_pixels if aoi_pixels else 0.0,
                "valid_rgb_fraction_of_aoi": master_valid / aoi_pixels if aoi_pixels else 0.0,
                "valid_pixel_count": master_valid,
                "aoi_pixel_count": aoi_pixels,
                "grid_pixel_count": grid.width * grid.height,
                "transparent_pixel_count": grid.width * grid.height - master_valid,
                "transparent_pixel_fraction": 1.0 - master_valid / (grid.width * grid.height),
            },
            "cog": web_metadata,
            "tonal_statistics": tonal_statistics,
            "file_sizes_bytes": {
                "rgb-reflectance.tif": (staging_dir / "rgb-reflectance.tif").stat().st_size,
                "rgb-web.tif": (staging_dir / "rgb-web.tif").stat().st_size,
                "rgb-quicklook.png": (staging_dir / "rgb-quicklook.png").stat().st_size,
            },
            "resource_telemetry": {
                "peak_max_rss_mib": round(telemetry.peak_mib, 2),
                "temporary_peak_bytes": peak_temp_bytes,
                "temporary_peak_mib": round(peak_temp_bytes / (1024 * 1024), 3),
                "elapsed_seconds": elapsed,
                "events": telemetry.events,
            },
            "reduction": reduction,
        }
        summary_base = {
            "year": year,
            "year_record": year_record,
            "aoi": {
                "west": config.aoi.west,
                "south": config.aoi.south,
                "east": config.aoi.east,
                "north": config.aoi.north,
            },
            "visualization_grid": {
                "crs": grid.crs,
                "resolution_m": grid.resolution,
                "bounds": list(grid.bounds),
                "width": grid.width,
                "height": grid.height,
                "transform": list(grid.transform),
                "aoi_pixel_count": aoi_pixels,
                "analytical_grid_note": (
                    "20 m analytical NBR/recovery grid remains unchanged; this is a 10 m "
                    "presentation grid"
                ),
            },
            "source": {
                "stac_endpoint": config.stac_endpoint,
                "collection": config.collection,
                "bands": list(RGB_BANDS),
                "inventory_path": str(inventory_path),
                "full_scene_download": False,
                "local_raw_cache": False,
            },
            "processing": {
                "acquisition_grouping": (
                    "UTC calendar date; same-date mosaic in (MGRS tile, Item ID) order"
                ),
                "temporal_composite": (
                    "exact per-pixel median independently for physical R, G, and B reflectance"
                ),
                "scl_invalid_classes": sorted(SCL_INVALID_CLASSES),
                "spectral_resampling": "average",
                "scl_resampling": "nearest-neighbour",
                "reflectance_scaling": (
                    "STAC raster:bands scale and offset applied before reprojection"
                ),
                "negative_reflectance": (
                    "finite negative RGB reflectance clamped to 0.0 for visualization only; "
                    "analytical REJECT defaults are unchanged"
                ),
                "display_black_point": config.rgb_black_point,
                "display_white_point": config.rgb_white_point,
                "gamma": config.rgb_gamma,
                "per_year_auto_stretch": False,
                "concurrency": "sequential years, acquisition dates, items, and bands",
                "gdal_cache_max_mib": 256,
            },
            "outputs": {
                "year_directory": str(output_dir),
                "reflectance_master": str(output_dir / "rgb-reflectance.tif"),
                "web_cog": str(output_dir / "rgb-web.tif"),
                "quicklook": str(output_dir / "rgb-quicklook.png"),
                "comparison_quicklook": str(output_root / "rgb-benchmark-comparison.png"),
            },
        }
        # Move only completed generated products into their year directory.
        for name in ("rgb-reflectance.tif", "rgb-web.tif", "rgb-quicklook.png"):
            os.replace(staging_dir / name, output_dir / name)
        _save_comparison(output_root)
        summary_path = output_root / "rgb-imagery-summary.json"
        _merge_summary(summary_path, summary_base)
        return summary_base
    except Exception as exc:
        last_memory = telemetry.events[-1]["max_rss_mib"] if telemetry.events else None
        print(
            f"RGB build failed for {year} at acquisition date {last_date or 'before acquisition'}; "
            f"last observed max RSS={last_memory} MiB: {type(exc).__name__}: {exc}",
            flush=True,
        )
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True, help="one explicit RGB benchmark year")
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--inventory", type=Path, default=Path("data/inventory/stac-items.json"))
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/web-imagery"))
    parser.add_argument("--temp-root", type=Path, default=Path("data/.tmp/rgb-imagery"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    summary = build(args.config, args.inventory, args.output_root, args.temp_root, args.year)
    record = summary["year_record"]
    print(
        f"Wrote {args.year} RGB COG; "
        f"valid coverage={record['valid_coverage']['rgb_percent']:.2f}%; "
        f"peak max RSS={record['resource_telemetry']['peak_max_rss_mib']:.2f} MiB",
        flush=True,
    )


if __name__ == "__main__":
    main()
