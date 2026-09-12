"""Build browser-delivery analytical COGs from approved local rasters.

The command is intentionally local-only.  It reads the canonical annual NBR
and recovery rasters, derives the fixed 2017-to-2018 spectral change layer,
and writes one shared EPSG:3857 float32 COG grid for all 21 outputs.  The
canonical EPSG:32633 rasters remain authoritative for numerical analysis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import Normalize
from rasterio.enums import MaskFlags, Resampling
from rasterio.transform import Affine, array_bounds
from rasterio.warp import calculate_default_transform, reproject

ANNUAL_YEARS = tuple(range(2017, 2027))
SOURCE_CRS = "EPSG:32633"
BROWSER_CRS = "EPSG:3857"
SOURCE_BOUNDS = (506260.0, 6858580.0, 531580.0, 6883240.0)
SOURCE_WIDTH = 1266
SOURCE_HEIGHT = 1233
SOURCE_RESOLUTION = 20.0
NODATA_VALUE = -9999.0
BLOCK_SIZE = 256
CONTINUOUS_RESAMPLING = Resampling.bilinear
MASK_RESAMPLING = Resampling.nearest
OVERVIEW_RESAMPLING = Resampling.average
RETAINED_DNBR_MIN = 0.30
RETAINED_BASELINE_MIN = 0.30
OUTPUT_ROOT_NAME = "web-delivery"
RASTER_MANIFEST_NAME = "raster-manifest.json"
WEB_DATA_MANIFEST = "data/derived/web-delivery/data/data-manifest.json"
IMAGERY_MANIFEST = "data/derived/web-delivery/imagery-manifest.json"


@dataclass(frozen=True)
class BrowserGrid:
    """The single frozen Web Mercator grid shared by every analytical COG."""

    crs: str
    transform: Affine
    width: int
    height: int
    bounds: tuple[float, float, float, float]

    @property
    def shape(self) -> tuple[int, int]:
        return self.height, self.width

    @property
    def pixel_size(self) -> tuple[float, float]:
        return float(self.transform.a), abs(float(self.transform.e))


class WebRasterBuildError(ValueError):
    """Raised when approved source or generated delivery validation fails."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def create_browser_grid() -> BrowserGrid:
    """Derive the analytical Web Mercator grid once from the approved grid."""
    transform, width, height = calculate_default_transform(
        SOURCE_CRS,
        BROWSER_CRS,
        SOURCE_WIDTH,
        SOURCE_HEIGHT,
        *SOURCE_BOUNDS,
    )
    bounds = tuple(float(value) for value in array_bounds(height, width, transform))
    return BrowserGrid(BROWSER_CRS, transform, width, height, bounds)


def expected_overview_levels(width: int, height: int) -> list[int]:
    """Match the GDAL COG driver's standard overview stopping rule."""
    levels: list[int] = []
    factor = 2
    while max(width, height) / factor >= 128:
        levels.append(factor)
        factor *= 2
    return levels


def browser_grid_record(grid: BrowserGrid) -> dict[str, Any]:
    """Return deterministic manifest metadata for the frozen destination grid."""
    return {
        "crs": grid.crs,
        "bounds": list(grid.bounds),
        "width": grid.width,
        "height": grid.height,
        "transform": list(grid.transform),
        "pixel_size": {
            "x": grid.pixel_size[0],
            "y": grid.pixel_size[1],
            "units": "EPSG:3857 map units per pixel",
        },
        "source_grid": {
            "crs": SOURCE_CRS,
            "bounds": list(SOURCE_BOUNDS),
            "width": SOURCE_WIDTH,
            "height": SOURCE_HEIGHT,
            "resolution_m": SOURCE_RESOLUTION,
        },
        "block_size": [BLOCK_SIZE, BLOCK_SIZE],
        "overview_levels": expected_overview_levels(grid.width, grid.height),
        "continuous_resampling": CONTINUOUS_RESAMPLING.name,
        "mask_resampling": MASK_RESAMPLING.name,
        "overview_resampling": OVERVIEW_RESAMPLING.name,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _source_paths(repo_root: Path) -> dict[str, Any]:
    annual = {
        year: repo_root / "data" / "derived" / "annual" / str(year) / "nbr.tif"
        for year in ANNUAL_YEARS
    }
    recovery = {
        year: repo_root / "data" / "derived" / "recovery" / "rasters" / f"recovery_{year}.tif"
        for year in ANNUAL_YEARS
    }
    return {
        "annual": annual,
        "recovery": recovery,
        "disturbance_mask": repo_root / "data" / "derived" / "disturbance" / "disturbance_mask.tif",
        "disturbance_labels": repo_root
        / "data"
        / "derived"
        / "disturbance"
        / "disturbance_labels.tif",
        "web_data_manifest": repo_root / WEB_DATA_MANIFEST,
        "imagery_manifest": repo_root / IMAGERY_MANIFEST,
    }


def _validate_output_root(output_root: Path, repo_root: Path) -> None:
    candidate = output_root.resolve()
    forbidden = (
        repo_root / "data" / "derived" / "annual",
        repo_root / "data" / "derived" / "recovery",
        repo_root / "data" / "derived" / "disturbance",
        repo_root / "data" / "derived" / "prototype",
        repo_root / "data" / "derived" / "web-imagery",
    )
    if any(
        candidate == path.resolve() or path.resolve() in candidate.parents for path in forbidden
    ):
        raise WebRasterBuildError("web raster output cannot target analytical source data")
    if candidate.name != OUTPUT_ROOT_NAME:
        raise WebRasterBuildError(f"output root must be named {OUTPUT_ROOT_NAME!r}")


def _validate_source_grid(dataset: rasterio.DatasetReader, path: Path) -> None:
    expected_transform = Affine(
        SOURCE_RESOLUTION, 0, SOURCE_BOUNDS[0], 0, -SOURCE_RESOLUTION, SOURCE_BOUNDS[3]
    )
    if str(dataset.crs) != SOURCE_CRS:
        raise WebRasterBuildError(f"{path} has CRS {dataset.crs}; expected {SOURCE_CRS}")
    if (dataset.width, dataset.height) != (SOURCE_WIDTH, SOURCE_HEIGHT):
        raise WebRasterBuildError(f"{path} dimensions do not match the approved analytical grid")
    if not np.allclose(tuple(dataset.bounds), SOURCE_BOUNDS, atol=1e-7):
        raise WebRasterBuildError(f"{path} bounds do not match the approved analytical grid")
    if not np.allclose(tuple(dataset.transform), tuple(expected_transform), atol=1e-9):
        raise WebRasterBuildError(f"{path} transform does not match the approved analytical grid")


def _read_float_source(
    path: Path, *, grid: BrowserGrid | None = None
) -> tuple[np.ndarray, np.ndarray]:
    if not path.is_file():
        raise FileNotFoundError(f"required source raster is missing: {path}")
    with rasterio.open(path) as dataset:
        if grid is None:
            _validate_source_grid(dataset, path)
        if dataset.count != 1 or dataset.dtypes != ("float32",):
            raise WebRasterBuildError(f"{path} must be one float32 band")
        if dataset.nodata != NODATA_VALUE:
            raise WebRasterBuildError(f"{path} must use nodata {NODATA_VALUE}")
        values = dataset.read(1).astype(np.float32, copy=False)
        valid = np.isfinite(values) & (values != NODATA_VALUE)
    return values, valid


def _read_footprint(paths: dict[str, Any]) -> np.ndarray:
    mask_path = paths["disturbance_mask"]
    labels_path = paths["disturbance_labels"]
    if not mask_path.is_file() or not labels_path.is_file():
        raise FileNotFoundError("disturbance mask and labels are required")
    with rasterio.open(mask_path) as mask_ds:
        _validate_source_grid(mask_ds, mask_path)
        if mask_ds.count != 1 or mask_ds.dtypes[0] != "uint8":
            raise WebRasterBuildError("disturbance mask must be one uint8 band")
        mask = mask_ds.read(1)
        mask_valid = (
            mask != mask_ds.nodata if mask_ds.nodata is not None else np.ones(mask.shape, bool)
        )
    with rasterio.open(labels_path) as labels_ds:
        _validate_source_grid(labels_ds, labels_path)
        if labels_ds.count != 1:
            raise WebRasterBuildError("disturbance labels must be one band")
        labels = labels_ds.read(1)
        label_valid = labels != labels_ds.nodata if labels_ds.nodata is not None else labels > 0
    retained = mask_valid & (mask == 1)
    labelled = label_valid & (labels > 0)
    if not np.array_equal(retained, labelled):
        raise WebRasterBuildError("disturbance mask and positive labels do not match")
    if sorted(int(value) for value in np.unique(labels[labelled])) != list(range(1, 81)):
        raise WebRasterBuildError("disturbance labels must contain exactly 1..80")
    return retained


def validate_inputs(
    paths: dict[str, Any],
) -> tuple[np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]]]:
    """Validate every approved input and return the fixed footprint and NBR inputs."""
    footprint = _read_footprint(paths)
    annual: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for year in ANNUAL_YEARS:
        annual[year] = _read_float_source(paths["annual"][year])
    recovery: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for year in ANNUAL_YEARS:
        values, valid = _read_float_source(paths["recovery"][year])
        if np.any(valid & ~footprint):
            raise WebRasterBuildError(
                f"recovery {year} is valid outside the retained disturbance footprint"
            )
        recovery[year] = (values, valid & footprint)
    for manifest_key in ("web_data_manifest", "imagery_manifest"):
        if not paths[manifest_key].is_file():
            raise FileNotFoundError(f"required manifest is missing: {paths[manifest_key]}")
    return footprint, {year: (annual[year][0], annual[year][1]) for year in ANNUAL_YEARS} | {
        year + 10000: recovery[year] for year in ANNUAL_YEARS
    }


def capture_input_hashes(paths: dict[str, Any]) -> dict[str, str]:
    """Hash all canonical inputs and the existing web-data/imagery manifests."""
    entries: dict[str, Path] = {}
    for year in ANNUAL_YEARS:
        entries[f"data/derived/annual/{year}/nbr.tif"] = paths["annual"][year]
        entries[f"data/derived/recovery/rasters/recovery_{year}.tif"] = paths["recovery"][year]
    entries["data/derived/disturbance/disturbance_mask.tif"] = paths["disturbance_mask"]
    entries["data/derived/disturbance/disturbance_labels.tif"] = paths["disturbance_labels"]
    entries[WEB_DATA_MANIFEST] = paths["web_data_manifest"]
    entries[IMAGERY_MANIFEST] = paths["imagery_manifest"]
    missing = [relative for relative, path in entries.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"required input files are missing: {missing}")
    return {relative: _sha256(entries[relative]) for relative in sorted(entries)}


def derive_dnbr(
    nbr_2017: np.ndarray,
    nbr_2018: np.ndarray,
    valid_2017: np.ndarray,
    valid_2018: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Derive exactly NBR_2017 - NBR_2018 where both source pixels are valid."""
    valid = np.asarray(valid_2017, dtype=bool) & np.asarray(valid_2018, dtype=bool)
    result = np.full(np.asarray(nbr_2017).shape, NODATA_VALUE, dtype=np.float32)
    result[valid] = (
        np.asarray(nbr_2017, dtype=np.float32)[valid]
        - np.asarray(nbr_2018, dtype=np.float32)[valid]
    ).astype(np.float32)
    return result, valid


def _reproject_continuous(
    values: np.ndarray, source_valid: np.ndarray, source_transform: Affine, grid: BrowserGrid
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reproject values with valid-weight normalization and a nearest mask.

    Weight-normalized bilinear reprojection avoids nodata bleed.  The separate
    nearest-neighbour mask prevents interpolated bridges across missing areas.
    The third return value is the nearest mask before the weight check, useful
    for spatial mask QA.
    """
    valid_float = source_valid.astype(np.float32)
    weighted_source = np.where(source_valid, values, 0.0).astype(np.float32)
    weighted = np.zeros(grid.shape, dtype=np.float32)
    weights = np.zeros(grid.shape, dtype=np.float32)
    nearest = np.zeros(grid.shape, dtype=np.uint8)
    common = {
        "src_transform": source_transform,
        "src_crs": SOURCE_CRS,
        "dst_transform": grid.transform,
        "dst_crs": BROWSER_CRS,
        "dst_nodata": 0.0,
        "init_dest_nodata": True,
        "resampling": CONTINUOUS_RESAMPLING,
    }
    reproject(weighted_source, weighted, **common)
    reproject(valid_float, weights, **common)
    reproject(
        source_valid.astype(np.uint8) * 255,
        nearest,
        src_transform=source_transform,
        src_crs=SOURCE_CRS,
        dst_transform=grid.transform,
        dst_crs=BROWSER_CRS,
        src_nodata=0,
        dst_nodata=0,
        init_dest_nodata=True,
        resampling=MASK_RESAMPLING,
    )
    valid = (nearest == 255) & (weights > 1e-6) & np.isfinite(weights)
    output = np.full(grid.shape, NODATA_VALUE, dtype=np.float32)
    output[valid] = weighted[valid] / weights[valid]
    valid &= np.isfinite(output) & (output != NODATA_VALUE)
    output[~valid] = NODATA_VALUE
    return output, valid, nearest == 255


def _windows(height: int, width: int):
    for row in range(0, height, BLOCK_SIZE):
        for col in range(0, width, BLOCK_SIZE):
            yield rasterio.windows.Window(
                col, row, min(BLOCK_SIZE, width - col), min(BLOCK_SIZE, height - row)
            )


def write_browser_cog(
    path: Path, values: np.ndarray, valid: np.ndarray, grid: BrowserGrid
) -> dict[str, Any]:
    """Write one tiled float32 COG with an internal validity mask."""
    values = np.asarray(values, dtype=np.float32)
    valid = np.asarray(valid, dtype=bool)
    if values.shape != grid.shape or valid.shape != grid.shape:
        raise ValueError("analytical COG values/mask do not match the frozen browser grid")
    output = np.full(grid.shape, NODATA_VALUE, dtype=np.float32)
    output[valid] = values[valid]
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="COG",
        width=grid.width,
        height=grid.height,
        count=1,
        dtype="float32",
        crs=BROWSER_CRS,
        transform=grid.transform,
        nodata=NODATA_VALUE,
        blocksize=BLOCK_SIZE,
        compress="DEFLATE",
        level=6,
        predictor=3,
        overview_resampling="average",
        BIGTIFF="IF_SAFER",
    ) as dataset:
        dataset.update_tags(
            ANALYTICAL_DTYPE="float32",
            CONTINUOUS_RESAMPLING=CONTINUOUS_RESAMPLING.name,
            MASK_RESAMPLING=MASK_RESAMPLING.name,
            DELIVERY_NOTE=(
                "Visualization/delivery derivative; canonical EPSG:32633 source "
                "remains authoritative"
            ),
            COLORIZATION="frontend",
        )
        for window in _windows(grid.height, grid.width):
            row = int(window.row_off)
            col = int(window.col_off)
            h = int(window.height)
            w = int(window.width)
            dataset.write(output[row : row + h, col : col + w], 1, window=window)
        dataset.write_mask(np.where(valid, 255, 0).astype(np.uint8))
    return validate_browser_cog(path, grid)


def _stats(
    values: np.ndarray, valid: np.ndarray, percentiles: tuple[int, ...] = (1, 50, 99)
) -> dict[str, float]:
    selected = np.asarray(values, dtype=np.float64)[np.asarray(valid, dtype=bool)]
    if selected.size == 0:
        return {
            "valid_fraction": 0.0,
            "min": None,
            **{f"p{p}": None for p in percentiles},
            "max": None,
        }
    result: dict[str, float] = {"valid_fraction": float(selected.size / np.asarray(valid).size)}
    result["min"] = float(np.min(selected))
    for percentile in percentiles:
        result[f"p{percentile}"] = float(np.percentile(selected, percentile))
    result["max"] = float(np.max(selected))
    return result


def _validate_mask_values(values: np.ndarray, mask: np.ndarray) -> bool:
    invalid = ~mask
    return bool(
        not np.any(values[invalid] != NODATA_VALUE)
        and np.all(np.isfinite(values[mask]))
    )


def validate_browser_cog(path: Path, grid: BrowserGrid) -> dict[str, Any]:
    """Validate COG layout, metadata, internal mask, overviews, and range proxies."""
    with rasterio.open(path) as dataset:
        values = dataset.read(1)
        mask = dataset.read_masks(1)
        overviews = dataset.overviews(1)
        structure = dataset.tags(ns="IMAGE_STRUCTURE")
        flags = dataset.mask_flag_enums[0]
        mask_is_internal = MaskFlags.per_dataset in flags and MaskFlags.alpha not in flags
        expected = expected_overview_levels(grid.width, grid.height)
        windows = []
        for row, col in ((0, 0), (grid.height // 2, grid.width // 2)):
            window = rasterio.windows.Window(
                max(0, col - 32), max(0, row - 32), min(64, grid.width), min(64, grid.height)
            )
            windows.append(int(dataset.read(1, window=window).size))
        overview_reads: list[dict[str, int]] = []
        for level in overviews[:1]:
            overview_height = max(1, (grid.height + level - 1) // level)
            overview_width = max(1, (grid.width + level - 1) // level)
            data = dataset.read(
                1, out_shape=(overview_height, overview_width), resampling=Resampling.nearest
            )
            overview_mask = dataset.read_masks(
                1, out_shape=(overview_height, overview_width), resampling=Resampling.nearest
            )
            overview_reads.append(
                {
                    "level": level,
                    "data_pixels": int(data.size),
                    "mask_pixels": int(overview_mask.size),
                }
            )
        valid = mask == 255
        result = {
            "valid": bool(
                dataset.driver == "GTiff"
                and structure.get("LAYOUT") == "COG"
                and str(dataset.crs) == BROWSER_CRS
                and (dataset.width, dataset.height) == (grid.width, grid.height)
                and np.allclose(tuple(dataset.transform), tuple(grid.transform), atol=1e-9)
                and dataset.count == 1
                and dataset.dtypes == ("float32",)
                and dataset.nodata == NODATA_VALUE
                and dataset.profile.get("tiled")
                and dataset.block_shapes == [(BLOCK_SIZE, BLOCK_SIZE)]
                and structure.get("COMPRESSION", "").upper() == "DEFLATE"
                and structure.get("PREDICTOR") == "3"
                and overviews == expected
                and mask_is_internal
                and set(np.unique(mask)).issubset({0, 255})
                and _validate_mask_values(values, valid)
                and len(windows) == 2
                and len(overview_reads) == len(expected[:1])
            ),
            "validation_method": (
                "GDAL COG layout plus Rasterio metadata, internal-mask, value, "
                "window, and overview readback"
            ),
            "driver": dataset.driver,
            "layout": structure.get("LAYOUT"),
            "crs": str(dataset.crs),
            "width": dataset.width,
            "height": dataset.height,
            "transform": list(dataset.transform),
            "bounds": list(dataset.bounds),
            "dtype": dataset.dtypes[0],
            "band_count": dataset.count,
            "nodata": dataset.nodata,
            "mask_flags": [flag.name for flag in flags],
            "internal_mask": mask_is_internal,
            "block_size": [dataset.block_shapes[0][1], dataset.block_shapes[0][0]],
            "compression": structure.get("COMPRESSION", str(dataset.compression).upper()),
            "predictor": structure.get("PREDICTOR"),
            "overview_levels": overviews,
            "overview_resampling": OVERVIEW_RESAMPLING.name,
            "file_size_bytes": path.stat().st_size,
            "valid_fraction": float(np.count_nonzero(valid) / valid.size),
            "range_read_window_pixel_counts": windows,
            "overview_read": overview_reads,
        }
    if not result["valid"]:
        raise WebRasterBuildError(f"COG validation failed for {path}: {result}")
    return result


def _reproject_source(
    path: Path, grid: BrowserGrid, footprint: np.ndarray | None = None
) -> dict[str, Any]:
    with rasterio.open(path) as dataset:
        source_transform = dataset.transform
        values = dataset.read(1).astype(np.float32, copy=False)
        nodata = dataset.nodata
    valid = np.isfinite(values) & (values != nodata)
    if footprint is not None:
        valid &= footprint
    browser_values, browser_valid, nearest = _reproject_continuous(
        values, valid, source_transform, grid
    )
    return {
        "values": browser_values,
        "valid": browser_valid,
        "nearest_valid": nearest,
        "source_values": values,
        "source_valid": valid,
    }


def _qa_record(
    source: dict[str, Any], browser_path: Path, *, percentiles: tuple[int, ...] = (1, 50, 99)
) -> dict[str, Any]:
    with rasterio.open(browser_path) as dataset:
        values = dataset.read(1)
        valid = dataset.read_masks(1) == 255
    source_stats = _stats(source["source_values"], source["source_valid"], percentiles)
    browser_stats = _stats(values, valid, percentiles)
    nearest = source["nearest_valid"]
    unexpected = int(np.count_nonzero(valid & ~nearest))
    lost_after_nearest = int(np.count_nonzero(nearest & ~valid))
    invalid_nodata_ok = _validate_mask_values(values, valid)
    return {
        "source_valid_fraction": source_stats["valid_fraction"],
        "browser_valid_fraction": browser_stats["valid_fraction"],
        "valid_fraction_difference": browser_stats["valid_fraction"]
        - source_stats["valid_fraction"],
        "source": source_stats,
        "browser": browser_stats,
        "mask_qa": {
            "nearest_expected_valid_fraction": float(np.count_nonzero(nearest) / nearest.size),
            "unexpected_expansion_pixels": unexpected,
            "nearest_valid_pixels_lost_to_zero_weight": lost_after_nearest,
            "no_spatial_expansion": unexpected == 0,
            "invalid_pixels_are_explicit_nodata": invalid_nodata_ok,
        },
    }


def _recovery_stats(values: np.ndarray, valid: np.ndarray) -> dict[str, Any]:
    result = _stats(values, valid)
    selected = values[valid]
    result["fraction_below_zero"] = (
        float(np.count_nonzero(selected < 0) / selected.size) if selected.size else 0.0
    )
    result["fraction_above_one"] = (
        float(np.count_nonzero(selected > 1) / selected.size) if selected.size else 0.0
    )
    return result


def _save_quicklook(
    path: Path,
    values: np.ndarray,
    valid: np.ndarray,
    title: str,
    cmap: str,
    vmin: float,
    vmax: float,
) -> None:
    figure, axis = plt.subplots(figsize=(8, 6), constrained_layout=True)
    try:
        masked = np.ma.masked_where(~valid, values)
        axis.imshow(
            masked, cmap=cmap, norm=Normalize(vmin=vmin, vmax=vmax, clip=True), origin="upper"
        )
        axis.set_title(f"{title} (QA colors only)")
        axis.set_axis_off()
        figure.savefig(path, dpi=120)
    finally:
        plt.close(figure)


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _manifest_reconciliation(paths: dict[str, Any]) -> dict[str, Any]:
    with paths["web_data_manifest"].open(encoding="utf-8") as file:
        web_data = json.load(file)
    with paths["imagery_manifest"].open(encoding="utf-8") as file:
        imagery = json.load(file)
    annual = web_data.get("annual_years")
    if annual != list(ANNUAL_YEARS):
        raise WebRasterBuildError("web-data manifest annual years do not match 2017..2026")
    if imagery.get("benchmark_years") != [2017, 2018, 2020, 2023, 2026]:
        raise WebRasterBuildError("imagery manifest benchmark years do not match the approved set")
    return {
        "annual_years": list(ANNUAL_YEARS),
        "benchmark_imagery_years": imagery["benchmark_years"],
    }


def build(repo_root: Path | None = None, *, force: bool = False) -> dict[str, Any]:
    """Build and validate the complete 21-raster package with no network access."""
    repo_root = (repo_root or _repo_root()).resolve()
    output_root = repo_root / "data" / "derived" / OUTPUT_ROOT_NAME
    _validate_output_root(output_root, repo_root)
    paths = _source_paths(repo_root)
    _manifest_reconciliation(paths)
    input_hashes = capture_input_hashes(paths)
    expected_outputs = [
        *(output_root / "rasters" / "nbr" / f"{year}.tif" for year in ANNUAL_YEARS),
        *(output_root / "rasters" / "recovery" / f"{year}.tif" for year in ANNUAL_YEARS),
        output_root / "rasters" / "change" / "dnbr-2017-2018.tif",
    ]
    existing = [path for path in expected_outputs if path.exists()]
    if existing and not force:
        raise WebRasterBuildError("generated analytical COGs already exist; rerun with --force")
    footprint, indexed = validate_inputs(paths)
    annual = {year: indexed[year] for year in ANNUAL_YEARS}
    grid = create_browser_grid()
    if (grid.width, grid.height) == (2544, 2482):
        raise WebRasterBuildError("analytical browser grid unexpectedly reused the 10 m RGB grid")

    records: dict[str, Any] = {"nbr": {}, "recovery": {}, "dnbr": {}}
    temp_root = output_root / ".raster-build-tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        for year in ANNUAL_YEARS:
            source_path = paths["annual"][year]
            converted = _reproject_source(source_path, grid)
            target = output_root / "rasters" / "nbr" / f"{year}.tif"
            temporary = temp_root / "nbr" / f"{year}.tif"
            cog = write_browser_cog(temporary, converted["values"], converted["valid"], grid)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, target)
            qa = _qa_record(converted, target)
            records["nbr"][str(year)] = {
                "year": year,
                "path": f"rasters/nbr/{year}.tif",
                "source": _relative(source_path, repo_root),
                "source_sha256": _sha256(source_path),
                "sha256": _sha256(target),
                "file_size_bytes": target.stat().st_size,
                "dtype": "float32",
                "nodata": NODATA_VALUE,
                "internal_mask": True,
                "units": "normalized difference burn ratio",
                "colorization": "frontend",
                "cog": cog,
                "qa": qa,
            }
        for year in ANNUAL_YEARS:
            source_path = paths["recovery"][year]
            converted = _reproject_source(source_path, grid, footprint)
            target = output_root / "rasters" / "recovery" / f"{year}.tif"
            temporary = temp_root / "recovery" / f"{year}.tif"
            cog = write_browser_cog(temporary, converted["values"], converted["valid"], grid)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, target)
            qa = _qa_record(converted, target)
            qa["browser"] = _recovery_stats(converted["values"], converted["valid"])
            records["recovery"][str(year)] = {
                "year": year,
                "path": f"rasters/recovery/{year}.tif",
                "source": _relative(source_path, repo_root),
                "source_sha256": _sha256(source_path),
                "sha256": _sha256(target),
                "file_size_bytes": target.stat().st_size,
                "dtype": "float32",
                "nodata": NODATA_VALUE,
                "internal_mask": True,
                "units": (
                    "NBR spectral recovery fraction (unbounded; masked to retained "
                    "disturbance pixels)"
                ),
                "colorization": "frontend",
                "cog": cog,
                "qa": qa,
            }
        dnbr_values, dnbr_valid = derive_dnbr(
            annual[2017][0], annual[2018][0], annual[2017][1], annual[2018][1]
        )
        retained_dnbr = dnbr_values[footprint]
        retained_baseline = annual[2017][0][footprint]
        if np.any(~np.isfinite(retained_dnbr)) or np.any(retained_dnbr < RETAINED_DNBR_MIN):
            raise WebRasterBuildError(
                "retained disturbance pixels fail the approved dNBR >= 0.30 criterion"
            )
        if np.any(~np.isfinite(retained_baseline)) or np.any(
            retained_baseline <= RETAINED_BASELINE_MIN
        ):
            raise WebRasterBuildError(
                "retained disturbance pixels fail the approved NBR_2017 > 0.30 criterion"
            )
        converted = _reproject_source(paths["annual"][2017], grid)
        dnbr_browser, dnbr_browser_valid, nearest_a = _reproject_continuous(
            dnbr_values,
            dnbr_valid,
            Affine(SOURCE_RESOLUTION, 0, SOURCE_BOUNDS[0], 0, -SOURCE_RESOLUTION, SOURCE_BOUNDS[3]),
            grid,
        )
        converted = {
            "values": dnbr_browser,
            "valid": dnbr_browser_valid,
            "nearest_valid": nearest_a,
            "source_values": dnbr_values,
            "source_valid": dnbr_valid,
        }
        target = output_root / "rasters" / "change" / "dnbr-2017-2018.tif"
        temporary = temp_root / "change" / "dnbr-2017-2018.tif"
        cog = write_browser_cog(temporary, dnbr_browser, dnbr_browser_valid, grid)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, target)
        qa = _qa_record(converted, target, percentiles=(50, 95, 99))
        with rasterio.open(target) as dataset:
            browser_values = dataset.read(1)
            browser_valid = dataset.read_masks(1) == 255
        records["dnbr"]["2017-2018"] = {
            "period": "2017-2018",
            "path": "rasters/change/dnbr-2017-2018.tif",
            "sources": [
                {
                    "path": _relative(paths["annual"][2017], repo_root),
                    "sha256": _sha256(paths["annual"][2017]),
                },
                {
                    "path": _relative(paths["annual"][2018], repo_root),
                    "sha256": _sha256(paths["annual"][2018]),
                },
            ],
            "sha256": _sha256(target),
            "file_size_bytes": target.stat().st_size,
            "dtype": "float32",
            "nodata": NODATA_VALUE,
            "internal_mask": True,
            "units": (
                "2017 to 2018 NBR difference; spectral change, not authoritative burn severity"
            ),
            "colorization": "frontend",
            "cog": cog,
            "qa": qa,
            "retained_disturbance_consistency": {
                "retained_pixel_count": int(footprint.sum()),
                "source_dnbr_min": float(np.min(retained_dnbr)),
                "source_baseline_nbr_2017_min": float(np.min(retained_baseline)),
                "all_dnbr_at_least_0_30": True,
                "all_baseline_nbr_2017_above_0_30": True,
                "browser_valid_fraction": float(
                    np.count_nonzero(browser_valid) / browser_valid.size
                ),
                "browser_min": float(np.min(browser_values[browser_valid])),
            },
        }

        quicklook_specs = [
            *(("nbr", year, "RdYlGn", -1.0, 1.0) for year in (2017, 2018, 2023, 2026)),
            *(("recovery", year, "coolwarm", -2.0, 2.0) for year in (2019, 2023, 2026)),
            ("dnbr", "2017-2018", "magma", 0.0, 1.0),
        ]
        quicklook_paths: list[str] = []
        for kind, identifier, cmap, vmin, vmax in quicklook_specs:
            if kind == "dnbr":
                path = output_root / "rasters" / "change" / "dnbr-2017-2018.tif"
                quicklook = output_root / "quicklooks" / "analytical-dnbr-2017-2018.png"
            else:
                path = output_root / "rasters" / kind / f"{identifier}.tif"
                quicklook = output_root / "quicklooks" / f"analytical-{kind}-{identifier}.png"
            with rasterio.open(path) as dataset:
                values = dataset.read(
                    1,
                    out_shape=(max(1, dataset.height // 2), max(1, dataset.width // 2)),
                    resampling=Resampling.nearest,
                )
                valid = (
                    dataset.read_masks(1, out_shape=values.shape, resampling=Resampling.nearest)
                    == 255
                )
            quicklook.parent.mkdir(parents=True, exist_ok=True)
            _save_quicklook(quicklook, values, valid, f"{kind} {identifier}", cmap, vmin, vmax)
            quicklook_paths.append(_relative(quicklook, repo_root))

        manifest = {
            "version": 1,
            "crs": BROWSER_CRS,
            "grid": browser_grid_record(grid),
            "layers": records,
            "annual_years": list(ANNUAL_YEARS),
            "benchmark_imagery_years": [2017, 2018, 2020, 2023, 2026],
            "source_integrity": input_hashes,
            "quicklooks": quicklook_paths,
            "provenance": {
                "network_processing": False,
                "canonical_analysis_crs": SOURCE_CRS,
                "canonical_analysis_resolution_m": SOURCE_RESOLUTION,
                "canonical_sources_authoritative": True,
                "delivery_note": (
                    "Browser COGs are visualization/delivery derivatives; use canonical "
                    "sources for exact numerical analysis"
                ),
                "browser_side_colorization": True,
                "recovery_caveat": (
                    "Recovery is unbounded and remains masked to retained disturbance "
                    "pixels; values are not clamped to [0,1]"
                ),
                "dnbr_interpretation": (
                    "2017 to 2018 spectral NBR change; not an authoritative burn-severity product"
                ),
            },
            "manifest_reconciliation": _manifest_reconciliation(paths),
        }
        manifest_path = output_root / RASTER_MANIFEST_NAME
        _write_manifest(manifest_path, manifest)
        if capture_input_hashes(paths) != input_hashes:
            raise WebRasterBuildError(
                "canonical input or existing web manifest hash changed during build"
            )
        return manifest
    finally:
        for child in sorted(temp_root.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        if temp_root.exists():
            temp_root.rmdir()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="replace existing generated analytical COGs"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = build(force=args.force)
    print(
        json.dumps(
            {"manifest": RASTER_MANIFEST_NAME, "rasters": 21, "grid": manifest["grid"]}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
