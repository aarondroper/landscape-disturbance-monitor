"""Build static MapLibre-oriented RGB COGs from local RGB masters.

This command is deliberately local-only.  It does not query STAC, read
remote assets, or rebuild a reflectance composite.  Each explicit benchmark
year is reprojected from its existing float32 ``rgb-reflectance.tif`` master
to one shared Web Mercator grid before the approved display transform is
encoded as a three-band RGB COG.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import rasterio
from matplotlib import pyplot as plt
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import Affine, array_bounds
from rasterio.warp import calculate_default_transform, reproject

from .build_rgb_imagery import (
    RGB_BLOCK_SIZE,
    SUPPORTED_RGB_YEARS,
    fixed_display_transform,
)
from .config import load_config

SOURCE_CRS = "EPSG:32633"
BROWSER_CRS = "EPSG:3857"
SOURCE_BOUNDS = (506260.0, 6858580.0, 531580.0, 6883240.0)
SOURCE_WIDTH = 2532
SOURCE_HEIGHT = 2466
NODATA_VALUE = 255
NODATA_TRIPLET = (255, 255, 255)
DELIVERY_ROOT_NAME = "web-delivery"
OVERVIEW_LEVELS = [2, 4, 8, 16]


@dataclass(frozen=True)
class BrowserGrid:
    """The one frozen, north-up grid shared by every browser COG."""

    crs: str
    transform: Affine
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    pixel_size_x: float
    pixel_size_y: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.height, self.width


class MemoryTelemetry:
    """Small native-process telemetry record used by the local conversion."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, stage: str) -> None:
        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        mib = value / 1024.0 if value < 10_000_000 else value / (1024.0 * 1024.0)
        event = {"stage": stage, "max_rss_mib": round(mib, 2)}
        self.events.append(event)
        print(f"memory {stage}: max_rss={event['max_rss_mib']:.2f} MiB", flush=True)

    @property
    def peak_mib(self) -> float:
        return max((float(event["max_rss_mib"]) for event in self.events), default=0.0)


def create_browser_grid() -> BrowserGrid:
    """Derive the destination grid once from the approved source geometry."""
    transform, width, height = calculate_default_transform(
        SOURCE_CRS,
        BROWSER_CRS,
        SOURCE_WIDTH,
        SOURCE_HEIGHT,
        *SOURCE_BOUNDS,
    )
    bounds = tuple(float(value) for value in array_bounds(height, width, transform))
    return BrowserGrid(
        crs=BROWSER_CRS,
        transform=transform,
        width=width,
        height=height,
        bounds=bounds,
        pixel_size_x=float(transform.a),
        pixel_size_y=abs(float(transform.e)),
    )


def browser_grid_record(grid: BrowserGrid) -> dict[str, Any]:
    """Return deterministic manifest-ready grid metadata."""
    return {
        "crs": grid.crs,
        "bounds": list(grid.bounds),
        "width": grid.width,
        "height": grid.height,
        "transform": list(grid.transform),
        "pixel_size": {
            "x": grid.pixel_size_x,
            "y": grid.pixel_size_y,
            "units": "EPSG:3857 map units per pixel",
        },
        "source_grid": {
            "crs": SOURCE_CRS,
            "bounds": list(SOURCE_BOUNDS),
            "width": SOURCE_WIDTH,
            "height": SOURCE_HEIGHT,
        },
        "overview_levels": list(OVERVIEW_LEVELS),
        "block_size": [RGB_BLOCK_SIZE, RGB_BLOCK_SIZE],
    }


def expected_overview_levels(width: int, height: int) -> list[int]:
    """Match the GDAL COG driver's overview stopping rule for this raster size."""
    levels: list[int] = []
    factor = 2
    largest = max(width, height)
    while largest / factor >= 128:
        levels.append(factor)
        factor *= 2
    return levels


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_source_master(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"canonical RGB reflectance master not found: {path}")
    with rasterio.open(path) as dataset:
        if str(dataset.crs) != SOURCE_CRS:
            raise ValueError(f"unexpected source CRS {dataset.crs}; expected {SOURCE_CRS}")
        if (dataset.width, dataset.height) != (SOURCE_WIDTH, SOURCE_HEIGHT):
            raise ValueError("source master dimensions do not match the approved RGB grid")
        if not np.allclose(tuple(dataset.bounds), SOURCE_BOUNDS, atol=1e-6):
            raise ValueError("source master bounds do not match the approved RGB grid")
        expected = (10.0, 0.0, SOURCE_BOUNDS[0], 0.0, -10.0, SOURCE_BOUNDS[3], 0.0, 0.0, 1.0)
        if not np.allclose(tuple(dataset.transform), expected, atol=1e-9):
            raise ValueError("source master transform does not match the approved RGB grid")
        if dataset.count != 3 or dataset.dtypes != ("float32",) * 3:
            raise ValueError("source master must be three float32 reflectance bands")
        if dataset.nodata != -9999.0:
            raise ValueError("source master must use the approved -9999 reflectance nodata")


def _validate_paths(config_path: Path, output_root: Path) -> None:
    """Prevent delivery output from colliding with canonical or analytical data."""
    repo_root = config_path.resolve().parents[1]
    candidate = output_root.resolve()
    forbidden_roots = [
        repo_root / "data" / "derived" / name
        for name in ("annual", "prototype", "disturbance", "recovery", "web-imagery")
    ]
    if any(candidate == root or root in candidate.parents for root in forbidden_roots):
        raise ValueError("web delivery output cannot target canonical RGB or analytical data")
    if candidate.name != DELIVERY_ROOT_NAME:
        raise ValueError(f"web delivery output root must be named {DELIVERY_ROOT_NAME!r}")


def _reproject_reflectance(
    master_path: Path, grid: BrowserGrid, telemetry: MemoryTelemetry | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Reproject physical reflectance and a nearest-neighbour validity mask."""
    with rasterio.open(master_path) as source:
        source_values = source.read().astype(np.float32, copy=False)
        nodata = float(source.nodata)
        source_valid = np.all(np.isfinite(source_values), axis=0) & np.all(
            source_values != nodata, axis=0
        )
        destination = np.full((3, *grid.shape), np.nan, dtype=np.float32)
        for band in range(3):
            reproject(
                source=source_values[band],
                destination=destination[band],
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=nodata,
                dst_transform=grid.transform,
                dst_crs=grid.crs,
                dst_nodata=np.nan,
                resampling=Resampling.average,
                init_dest_nodata=True,
            )
        source_mask = source_valid.astype(np.uint8)
        destination_mask = np.zeros(grid.shape, dtype=np.uint8)
        reproject(
            source=source_mask,
            destination=destination_mask,
            src_transform=source.transform,
            src_crs=source.crs,
            src_nodata=0,
            dst_transform=grid.transform,
            dst_crs=grid.crs,
            dst_nodata=0,
            resampling=Resampling.nearest,
            init_dest_nodata=True,
        )
    valid = (destination_mask == 1) & np.all(np.isfinite(destination), axis=0)
    destination[:, ~valid] = np.nan
    if telemetry is not None:
        telemetry.record("after EPSG:3857 reprojection and nearest validity mask")
    return destination, valid


def render_browser_rgb(
    reflectance: np.ndarray,
    valid: np.ndarray,
    *,
    black_point: float,
    white_point: float,
    gamma: float,
) -> tuple[np.ndarray, dict[str, int | float]]:
    """Render RGB and reserve all-white only for invalid pixels."""
    values = np.asarray(reflectance, dtype=np.float32)
    valid_mask = np.asarray(valid, dtype=bool) & np.all(np.isfinite(values), axis=0)
    rendered = fixed_display_transform(
        values,
        black_point=black_point,
        white_point=white_point,
        gamma=gamma,
    )
    valid_all_white = valid_mask & np.all(rendered == 255, axis=0)
    rendered[:, valid_all_white] = 254
    rendered[:, ~valid_mask] = NODATA_VALUE
    valid_count = int(np.count_nonzero(valid_mask))
    all_white_count = int(np.count_nonzero(valid_all_white))
    total = int(valid_mask.size)
    return rendered, {
        "valid_pixel_count": valid_count,
        "nodata_pixel_count": total - valid_count,
        "all_white_before_adjustment_count": all_white_count,
        "all_white_before_adjustment_fraction_of_valid": (
            all_white_count / valid_count if valid_count else 0.0
        ),
        "remapped_pixel_count": all_white_count,
        "remapped_fraction_of_valid": all_white_count / valid_count if valid_count else 0.0,
        "valid_fraction": valid_count / total if total else 0.0,
        "nodata_fraction": (total - valid_count) / total if total else 0.0,
    }


def _windows(height: int, width: int, block_size: int = RGB_BLOCK_SIZE):
    for row_off in range(0, height, block_size):
        for col_off in range(0, width, block_size):
            yield rasterio.windows.Window(
                col_off,
                row_off,
                min(block_size, width - col_off),
                min(block_size, height - row_off),
            )


def write_browser_cog(
    output_path: Path,
    rgb: np.ndarray,
    grid: BrowserGrid,
    *,
    black_point: float,
    white_point: float,
    gamma: float,
    telemetry: MemoryTelemetry | None = None,
) -> dict[str, Any]:
    """Write a tiled three-band RGB COG with an explicit shared nodata value."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    values = np.asarray(rgb, dtype=np.uint8)
    if values.shape != (3, *grid.shape):
        raise ValueError("browser RGB array does not match the frozen destination grid")
    with rasterio.open(
        output_path,
        "w",
        driver="COG",
        height=grid.height,
        width=grid.width,
        count=3,
        dtype="uint8",
        crs=grid.crs,
        transform=grid.transform,
        nodata=NODATA_VALUE,
        blocksize=RGB_BLOCK_SIZE,
        compress="DEFLATE",
        level=6,
        predictor=2,
        interleave="PIXEL",
        overview_resampling="average",
        BIGTIFF="IF_SAFER",
    ) as dataset:
        dataset.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
        dataset.update_tags(
            DISPLAY_BLACK_POINT=str(black_point),
            DISPLAY_WHITE_POINT=str(white_point),
            DISPLAY_GAMMA=str(gamma),
            NODATA_RGB_TRIPLET=",".join(str(value) for value in NODATA_TRIPLET),
            DELIVERY_ARCHITECTURE="MapLibre serverless COG protocol; no alpha band",
        )
        for window in _windows(grid.height, grid.width):
            row = int(window.row_off)
            col = int(window.col_off)
            height = int(window.height)
            width = int(window.width)
            dataset.write(values[:, row : row + height, col : col + width], window=window)
    if telemetry is not None:
        telemetry.record("after browser COG write")
    return validate_browser_cog(output_path, grid)


def validate_browser_cog(path: Path, grid: BrowserGrid) -> dict[str, Any]:
    """Validate COG structure, RGB/nodata semantics, and local window reads."""
    with rasterio.open(path) as dataset:
        structure = dataset.tags(ns="IMAGE_STRUCTURE")
        overviews = dataset.overviews(1)
        overview_sets = [dataset.overviews(index) for index in range(1, 4)]
        values = dataset.read()
        valid = np.any(values != NODATA_VALUE, axis=0)
        invalid = ~valid
        invalid_triplet = (
            bool(np.all(values[:, invalid] == NODATA_VALUE)) if np.any(invalid) else True
        )
        valid_all_white = int(np.count_nonzero(valid & np.all(values == NODATA_VALUE, axis=0)))
        window_checks = []
        for row, col in (
            (0, 0),
            (max(0, dataset.height // 2 - 32), max(0, dataset.width // 2 - 32)),
            (max(0, dataset.height - 64), max(0, dataset.width - 64)),
        ):
            window = rasterio.windows.Window(
                col, row, min(64, dataset.width - col), min(64, dataset.height - row)
            )
            window_checks.append(int(dataset.read(1, window=window).size))
        photometric = (
            "RGB"
            if dataset.colorinterp == (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
            else None
        )
        result = {
            "valid": (
                dataset.driver == "GTiff"
                and structure.get("LAYOUT") == "COG"
                and dataset.count == 3
                and dataset.dtypes == ("uint8",) * 3
                and str(dataset.crs) == BROWSER_CRS
                and dataset.nodata == float(NODATA_VALUE)
                and bool(dataset.profile.get("tiled"))
                and all(shape == (RGB_BLOCK_SIZE, RGB_BLOCK_SIZE) for shape in dataset.block_shapes)
                and photometric == "RGB"
                and overviews == expected_overview_levels(dataset.width, dataset.height)
                and overview_sets == [overviews] * 3
                and structure.get("COMPRESSION", "").upper() == "DEFLATE"
                and invalid_triplet
                and valid_all_white == 0
                and len(window_checks) == 3
            ),
            "validation_method": (
                "GDAL COG driver layout plus Rasterio metadata, full-pixel, overview, "
                "and window readback"
            ),
            "driver": dataset.driver,
            "layout": structure.get("LAYOUT"),
            "crs": str(dataset.crs),
            "width": dataset.width,
            "height": dataset.height,
            "transform": list(dataset.transform),
            "bounds": list(dataset.bounds),
            "band_count": dataset.count,
            "dtype": dataset.dtypes[0],
            "nodata": dataset.nodata,
            "photometric_interpretation": photometric,
            "color_interpretation": [value.name for value in dataset.colorinterp],
            "block_size": [dataset.block_shapes[0][1], dataset.block_shapes[0][0]],
            "compression": structure.get("COMPRESSION", str(dataset.compression).upper()),
            "overview_levels": overviews,
            "overview_resampling": structure.get("OVERVIEW_RESAMPLING"),
            "file_size_bytes": path.stat().st_size,
            "invalid_pixel_count": int(np.count_nonzero(invalid)),
            "invalid_triplet_ok": invalid_triplet,
            "valid_all_white_final_count": valid_all_white,
            "range_read_window_pixel_counts": window_checks,
            "no_alpha_band": dataset.count == 3
            and all(value != ColorInterp.alpha for value in dataset.colorinterp),
        }
    if not result["valid"]:
        raise ValueError(f"browser COG validation failed for {path}: {result}")
    return result


def validate_benchmark_alignment(paths: dict[int, Path], grid: BrowserGrid) -> dict[str, Any]:
    """Fail loudly if any browser COG differs from the frozen shared grid."""
    if tuple(sorted(paths)) != SUPPORTED_RGB_YEARS:
        raise ValueError(f"expected exactly benchmark years {SUPPORTED_RGB_YEARS}")
    metadata = {year: validate_browser_cog(path, grid) for year, path in sorted(paths.items())}
    reference = metadata[SUPPORTED_RGB_YEARS[0]]
    for year in SUPPORTED_RGB_YEARS[1:]:
        candidate = metadata[year]
        for key in (
            "crs",
            "width",
            "height",
            "bounds",
            "transform",
            "block_size",
            "overview_levels",
        ):
            if candidate[key] != reference[key]:
                raise ValueError(f"benchmark browser COG alignment mismatch for {year}: {key}")
    return {
        "valid": True,
        "years": list(SUPPORTED_RGB_YEARS),
        "identical_grid": True,
        "identical_overview_scheme": True,
        "cogs": {str(year): metadata[year] for year in SUPPORTED_RGB_YEARS},
    }


def _read_quicklook(path: Path, *, max_dimension: int = 1200) -> tuple[np.ndarray, np.ndarray]:
    with rasterio.open(path) as dataset:
        scale = min(1.0, max_dimension / max(dataset.width, dataset.height))
        height = max(1, int(round(dataset.height * scale)))
        width = max(1, int(round(dataset.width * scale)))
        values = dataset.read(
            indexes=(1, 2, 3),
            out_shape=(3, height, width),
            resampling=Resampling.nearest,
        )
        if dataset.count == 4:
            alpha = dataset.read(
                4, out_shape=(height, width), resampling=Resampling.nearest
            )
        else:
            alpha = np.where(np.any(values != NODATA_VALUE, axis=0), 255, 0).astype(np.uint8)
    return values, alpha


def _save_quicklook(path: Path, values: np.ndarray, alpha: np.ndarray, title: str) -> None:
    figure, axis = plt.subplots(figsize=(9, 7), constrained_layout=True)
    try:
        axis.imshow(np.moveaxis(values, 0, -1), origin="upper", alpha=alpha / 255.0)
        axis.set_title(title)
        axis.set_axis_off()
        figure.savefig(path, dpi=120)
    finally:
        plt.close(figure)


def _save_comparison(path: Path, canonical: Path, browser: Path, year: int) -> dict[str, Any]:
    canonical_values, canonical_alpha = _read_quicklook(canonical)
    browser_values, browser_alpha = _read_quicklook(browser)
    height = min(canonical_values.shape[1], browser_values.shape[1])
    width = min(canonical_values.shape[2], browser_values.shape[2])
    canonical_values = canonical_values[:, :height, :width]
    browser_values = browser_values[:, :height, :width]
    common = (canonical_alpha[:height, :width] > 0) & (browser_alpha[:height, :width] > 0)
    difference = np.abs(canonical_values.astype(np.int16) - browser_values.astype(np.int16))
    common_count = int(np.count_nonzero(common))
    mean_difference = float(difference[:, common].mean()) if common_count else 0.0
    p95_difference = float(np.percentile(difference[:, common], 95)) if common_count else 0.0
    figure, axes = plt.subplots(1, 2, figsize=(15, 7), constrained_layout=True)
    try:
        axes[0].imshow(
            np.moveaxis(canonical_values, 0, -1),
            origin="upper",
            alpha=canonical_alpha[:height, :width] / 255.0,
        )
        axes[0].set_title(f"{year} canonical EPSG:32633")
        axes[1].imshow(
            np.moveaxis(browser_values, 0, -1),
            origin="upper",
            alpha=browser_alpha[:height, :width] / 255.0,
        )
        axes[1].set_title(f"{year} browser EPSG:3857")
        for axis in axes:
            axis.set_axis_off()
        figure.savefig(path, dpi=120)
    finally:
        plt.close(figure)
    return {
        "common_valid_fraction_of_comparison": (
            common_count / (height * width) if height and width else 0.0
        ),
        "mean_absolute_rgb_difference": round(mean_difference, 3),
        "p95_absolute_rgb_difference": round(p95_difference, 3),
        "assessment": "materially preserved" if mean_difference <= 12 else "review required",
    }


def _update_manifest(path: Path, grid: BrowserGrid, record: dict[str, Any]) -> None:
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    imagery = dict(existing.get("imagery", {}))
    imagery[str(record["year"])] = record
    payload = {
        "version": 1,
        "crs": BROWSER_CRS,
        "benchmark_years": list(SUPPORTED_RGB_YEARS),
        "display": {
            "black": record["display"]["black"],
            "white": record["display"]["white"],
            "gamma": record["display"]["gamma"],
        },
        "grid": browser_grid_record(grid),
        "imagery": {year: imagery[year] for year in sorted(imagery, key=int)},
        "provenance": {
            "canonical_root": "data/derived/web-imagery",
            "delivery_root": "data/derived/web-delivery",
            "network_processing": False,
            "source_note": "Existing approved local RGB reflectance masters only",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build(
    config_path: Path,
    source_root: Path,
    output_root: Path,
    year: int,
) -> dict[str, Any]:
    """Convert exactly one explicitly requested benchmark year."""
    if year not in SUPPORTED_RGB_YEARS:
        raise ValueError(f"unsupported year {year}; choose one of {SUPPORTED_RGB_YEARS}")
    _validate_paths(config_path, output_root)
    config = load_config(config_path)
    if tuple(config.benchmark_years) != SUPPORTED_RGB_YEARS:
        raise ValueError("configuration benchmark years do not match the approved delivery set")
    if (config.rgb_black_point, config.rgb_white_point, config.rgb_gamma) != (0.01, 0.22, 1.0):
        raise ValueError("browser delivery requires the approved 0.01–0.22/gamma 1.0 transform")
    started = time.perf_counter()
    telemetry = MemoryTelemetry()
    grid = create_browser_grid()
    source_path = source_root / str(year) / "rgb-reflectance.tif"
    canonical_web_path = source_root / str(year) / "rgb-web.tif"
    _validate_source_master(source_path)
    output_path = output_root / "imagery" / str(year) / "rgb.tif"
    if output_path.resolve() in {source_path.resolve(), canonical_web_path.resolve()}:
        raise ValueError("browser delivery output would overwrite a canonical RGB input")
    output_root.mkdir(parents=True, exist_ok=True)
    telemetry.record("after local input validation")
    reflectance, valid = _reproject_reflectance(source_path, grid, telemetry)
    rgb, nodata_stats = render_browser_rgb(
        reflectance,
        valid,
        black_point=config.rgb_black_point,
        white_point=config.rgb_white_point,
        gamma=config.rgb_gamma,
    )
    telemetry.record("after fixed RGB render and nodata reservation")
    with tempfile.TemporaryDirectory(prefix=f".{year}-", dir=output_root) as temp_dir:
        temporary_output = Path(temp_dir) / "rgb.tif"
        cog = write_browser_cog(
            temporary_output,
            rgb,
            grid,
            black_point=config.rgb_black_point,
            white_point=config.rgb_white_point,
            gamma=config.rgb_gamma,
            telemetry=telemetry,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary_output, output_path)
    quicklook_dir = output_root / "quicklooks"
    quicklook_dir.mkdir(parents=True, exist_ok=True)
    browser_values, browser_alpha = _read_quicklook(output_path)
    quicklook_path = quicklook_dir / f"{year}-browser.png"
    _save_quicklook(quicklook_path, browser_values, browser_alpha, f"{year} browser RGB")
    comparison_path = quicklook_dir / f"{year}-comparison.png"
    comparison = _save_comparison(comparison_path, canonical_web_path, output_path, year)
    telemetry.record("after quicklooks")
    telemetry.record("build end")
    source_relative = Path("data/derived/web-imagery") / str(year) / "rgb-reflectance.tif"
    canonical_relative = Path("data/derived/web-imagery") / str(year) / "rgb-web.tif"
    record = {
        "year": year,
        "path": (Path("imagery") / str(year) / "rgb.tif").as_posix(),
        "source": source_relative.as_posix(),
        "canonical_presentation_source": canonical_relative.as_posix(),
        "source_sha256": _sha256(source_path),
        "canonical_presentation_sha256": _sha256(canonical_web_path),
        "valid_fraction": nodata_stats["valid_fraction"],
        "nodata_fraction": nodata_stats["nodata_fraction"],
        "file_size_bytes": output_path.stat().st_size,
        "display": {"black": 0.01, "white": 0.22, "gamma": 1.0},
        "nodata": {
            "value": NODATA_VALUE,
            "rgb_triplet": list(NODATA_TRIPLET),
            **nodata_stats,
        },
        "cog": cog,
        "quicklook": (Path("quicklooks") / f"{year}-browser.png").as_posix(),
        "comparison_quicklook": (Path("quicklooks") / f"{year}-comparison.png").as_posix(),
        "visual_comparison": comparison,
        "resource_telemetry": {
            "peak_rss_mib": round(telemetry.peak_mib, 2),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "temporary_disk_peak_bytes": cog["file_size_bytes"],
            "events": telemetry.events,
        },
    }
    _update_manifest(output_root / "imagery-manifest.json", grid, record)
    return {
        "grid": browser_grid_record(grid),
        "record": record,
        "manifest": str(output_root / "imagery-manifest.json"),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True, help="one explicit benchmark year")
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--source-root", type=Path, default=Path("data/derived/web-imagery"))
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/web-delivery"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    result = build(args.config, args.source_root, args.output_root, args.year)
    record = result["record"]
    print(
        f"Wrote {record['path']}; valid={record['valid_fraction']:.6f}; "
        f"remapped={record['nodata']['remapped_pixel_count']} "
        f"({record['nodata']['remapped_fraction_of_valid']:.8f}); "
        f"peak RSS={record['resource_telemetry']['peak_rss_mib']:.2f} MiB",
        flush=True,
    )


if __name__ == "__main__":
    main()
