"""Build one exact, disk-backed annual Sentinel-2 index composite.

This command intentionally accepts exactly one explicit year per process.  It
first writes one AOI-only NBR/NDVI GeoTIFF per usable acquisition date, then
computes the exact temporal median one spatial block at a time.  Acquisition
rasters are never collected into a full-AOI temporal stack in RAM.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import tempfile
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np
import rasterio
from matplotlib import pyplot as plt
from matplotlib.colors import Normalize
from rasterio.windows import Window

from .build_composite_prototype import _asset, load_inventory
from .composite_prototype import (
    ANALYSIS_CRS,
    ANALYSIS_RESOLUTION,
    COUNT_NODATA,
    FLOAT_NODATA,
    AnalysisGrid,
    ReflectanceTreatment,
    create_analysis_grid,
    distribution,
    group_acquisition_items,
    is_usable_acquisition,
    normalize_reflectance_treatment,
    read_asset_metadata,
    read_item_indices,
    valid_count_distribution,
)
from .config import ProjectConfig, load_config

APPROVED_BOUNDS = (506260.0, 6858580.0, 531580.0, 6883240.0)
APPROVED_WIDTH = 1266
APPROVED_HEIGHT = 1233
BLOCK_SIZE = 256
PROCESSING_BANDS = ("red", "nir", "swir2", "scl")


@dataclass(frozen=True)
class TemporaryAcquisition:
    date: str
    nbr_path: Path
    ndvi_path: Path


def _linux_peak_rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports KiB; macOS reports bytes.  The build target is Linux/WSL,
    # but keeping this portable makes the telemetry helper deterministic in CI.
    return value / 1024.0 if value < 10_000_000 else value / (1024.0 * 1024.0)


class MemoryTelemetry:
    """Small native-process peak-RSS log using getrusage high-water marks."""

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


@contextmanager
def temporary_workspace(
    root: Path, year: int, *, keep_on_error: bool = False
) -> Iterator[Path]:
    """Create and clean one uniquely-owned temporary annual workspace."""
    root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix=f"{year}-", dir=root))
    try:
        yield run_dir
    except Exception:
        if keep_on_error:
            print(f"Temporary diagnostic workspace retained at {run_dir}", flush=True)
        else:
            shutil.rmtree(run_dir, ignore_errors=True)
        raise
    else:
        shutil.rmtree(run_dir, ignore_errors=True)


def _approved_grid(config: ProjectConfig) -> AnalysisGrid:
    grid = create_analysis_grid(config.aoi)
    if (
        grid.crs != ANALYSIS_CRS
        or grid.resolution != ANALYSIS_RESOLUTION
        or grid.bounds != APPROVED_BOUNDS
        or grid.width != APPROVED_WIDTH
        or grid.height != APPROVED_HEIGHT
    ):
        raise ValueError("configured analysis grid does not match the canonical analysis grid")
    return grid


def validate_output_grid(dataset: rasterio.DatasetReader, grid: AnalysisGrid, path: Path) -> None:
    """Reject an output whose CRS, transform, dimensions, or bounds drifted."""
    if str(dataset.crs) != grid.crs:
        raise ValueError(f"{path} has CRS {dataset.crs}, expected {grid.crs}")
    if (dataset.width, dataset.height) != (grid.width, grid.height):
        raise ValueError(
            f"{path} has dimensions {(dataset.width, dataset.height)}, "
            f"expected {grid.shape[::-1]}"
        )
    if not np.allclose(tuple(dataset.transform), tuple(grid.transform), atol=1e-9):
        raise ValueError(f"{path} has a transform different from the approved grid")
    if not np.allclose(tuple(dataset.bounds), grid.bounds, atol=1e-6):
        raise ValueError(f"{path} has bounds {tuple(dataset.bounds)}, expected {grid.bounds}")


def _is_https_cog(item: dict[str, Any], band: str) -> bool:
    return any(
        asset.get("cog_likely") and str(asset.get("href", "")).startswith("https://")
        for asset in item.get("relevant_assets", {}).get(band, [])
    )


def _processable(item: dict[str, Any]) -> bool:
    return all(_is_https_cog(item, band) for band in PROCESSING_BANDS)


def _scale_offset_summary(
    items: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, float | None]]]:
    result: dict[str, list[dict[str, float | None]]] = {}
    for band in PROCESSING_BANDS:
        pairs = {
            (
                read_asset_metadata(_asset(item, band))["scale"],
                read_asset_metadata(_asset(item, band))["offset"],
            )
            for item in items
            if item.get("relevant_assets", {}).get(band)
        }
        result[band] = [
            {"scale": scale, "offset": offset} for scale, offset in sorted(pairs, key=str)
        ]
    return result


def _profile(
    grid: AnalysisGrid, *, dtype: str, nodata: float | int, predictor: int
) -> dict[str, Any]:
    return {
        "driver": "GTiff",
        "height": grid.height,
        "width": grid.width,
        "count": 1,
        "dtype": dtype,
        "crs": grid.crs,
        "transform": grid.transform,
        "nodata": nodata,
        "tiled": True,
        "blockxsize": BLOCK_SIZE,
        "blockysize": BLOCK_SIZE,
        "compress": "deflate",
        "predictor": predictor,
        "BIGTIFF": "IF_SAFER",
    }


def _write_full_temp(path: Path, values: np.ndarray, grid: AnalysisGrid) -> None:
    output = np.where(np.isfinite(values) & grid.aoi_mask, values, FLOAT_NODATA).astype(
        np.float32, copy=False
    )
    with rasterio.open(
        path,
        "w",
        **_profile(grid, dtype="float32", nodata=FLOAT_NODATA, predictor=3),
    ) as dataset:
        dataset.write(output, 1)


def _windows(grid: AnalysisGrid) -> Iterator[Window]:
    for row_off in range(0, grid.height, BLOCK_SIZE):
        for col_off in range(0, grid.width, BLOCK_SIZE):
            yield Window(
                col_off,
                row_off,
                min(BLOCK_SIZE, grid.width - col_off),
                min(BLOCK_SIZE, grid.height - row_off),
            )


def _read_float_block(dataset: rasterio.DatasetReader, window: Window) -> np.ndarray:
    values = dataset.read(1, window=window, masked=False).astype(np.float32, copy=False)
    if dataset.nodata is not None:
        values[values == dataset.nodata] = np.nan
    values[~np.isfinite(values)] = np.nan
    return values


def exact_block_median(observations: Sequence[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Return an exact float32 NaN-median and uint16 valid count for one block."""
    if not observations:
        raise ValueError("at least one block observation is required")
    stack = np.stack([np.asarray(observation, dtype=np.float32) for observation in observations])
    valid_count = np.sum(np.isfinite(stack), axis=0, dtype=np.uint16)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        median = np.nanmedian(stack, axis=0).astype(np.float32, copy=False)
    median[valid_count == 0] = np.nan
    return median, valid_count


def _mosaic_into(
    destination: np.ndarray,
    filled: np.ndarray,
    values: np.ndarray,
    valid: np.ndarray,
) -> None:
    select = np.asarray(valid, dtype=bool) & np.isfinite(values) & ~filled
    destination[select] = np.asarray(values, dtype=np.float32)[select]
    filled[select] = True


def _process_acquisition(
    acquisition_date: str,
    items: list[dict[str, Any]],
    grid: AnalysisGrid,
    workspace: Path,
    telemetry: MemoryTelemetry,
    treatment: ReflectanceTreatment,
) -> tuple[TemporaryAcquisition | None, dict[str, Any]]:
    """Read one date sequentially and write only its derived arrays to disk."""
    print(f"{acquisition_date}: reading {len(items)} item(s)", flush=True)
    date_nbr = np.full(grid.shape, np.nan, dtype=np.float32)
    date_ndvi = np.full(grid.shape, np.nan, dtype=np.float32)
    nbr_filled = np.zeros(grid.shape, dtype=bool)
    ndvi_filled = np.zeros(grid.shape, dtype=bool)

    for item in items:
        result = read_item_indices(item, grid, _asset, treatment=treatment)
        _mosaic_into(date_nbr, nbr_filled, result["nbr"], result["nbr_mask"])
        _mosaic_into(date_ndvi, ndvi_filled, result["ndvi"], result["ndvi_mask"])
        del result

    valid_nbr = int(np.count_nonzero(nbr_filled & grid.aoi_mask))
    valid_ndvi = int(np.count_nonzero(ndvi_filled & grid.aoi_mask))
    aoi_pixels = int(np.count_nonzero(grid.aoi_mask))
    record = {
        "date": acquisition_date,
        "item_ids": [item["id"] for item in items],
        "acquisition_datetimes": [item.get("datetime") for item in items],
        "mgrs_tiles": sorted({str(item.get("mgrs_tile")) for item in items}),
        "scene_cloud_cover": [item.get("eo:cloud_cover") for item in items],
        "valid_pixel_count": valid_nbr,
        "valid_pixel_percentage": 100.0 * valid_nbr / aoi_pixels if aoi_pixels else 0.0,
        "ndvi_valid_pixel_count": valid_ndvi,
        "ndvi_valid_pixel_percentage": 100.0 * valid_ndvi / aoi_pixels if aoi_pixels else 0.0,
        "mosaic_rule": "first valid pixel in (MGRS tile, Item ID) order; no averaging",
    }
    if valid_nbr == 0 and valid_ndvi == 0:
        del date_nbr, date_ndvi, nbr_filled, ndvi_filled
        telemetry.record(f"after acquisition {acquisition_date} (no valid pixels)")
        return None, record

    index = len(list(workspace.glob("*_nbr.tif")))
    safe_date = acquisition_date.replace("-", "")
    nbr_path = workspace / f"{index:03d}_{safe_date}_nbr.tif"
    ndvi_path = workspace / f"{index:03d}_{safe_date}_ndvi.tif"
    _write_full_temp(nbr_path, date_nbr, grid)
    _write_full_temp(ndvi_path, date_ndvi, grid)
    del date_nbr, date_ndvi, nbr_filled, ndvi_filled
    telemetry.record(f"after acquisition {acquisition_date}")
    return TemporaryAcquisition(acquisition_date, nbr_path, ndvi_path), record


def _write_block_outputs(
    acquisitions: Sequence[TemporaryAcquisition],
    grid: AnalysisGrid,
    nbr_path: Path,
    ndvi_path: Path,
    valid_count_path: Path,
    telemetry: MemoryTelemetry,
) -> dict[str, Any]:
    """Reduce temporary date rasters in 256x256 exact-median blocks."""
    if not acquisitions:
        raise ValueError("cannot reduce a year with no usable acquisition rasters")
    with (
        rasterio.open(
            nbr_path,
            "w",
            **_profile(grid, dtype="float32", nodata=FLOAT_NODATA, predictor=3),
        ) as nbr_out,
        rasterio.open(
            ndvi_path,
            "w",
            **_profile(grid, dtype="float32", nodata=FLOAT_NODATA, predictor=3),
        ) as ndvi_out,
        rasterio.open(
            valid_count_path,
            "w",
            **_profile(grid, dtype="uint16", nodata=COUNT_NODATA, predictor=2),
        ) as count_out,
    ):
        nbr_datasets = [rasterio.open(acquisition.nbr_path) for acquisition in acquisitions]
        ndvi_datasets = [rasterio.open(acquisition.ndvi_path) for acquisition in acquisitions]
        try:
            block_count = 0
            for window in _windows(grid):
                row = int(window.row_off)
                col = int(window.col_off)
                height = int(window.height)
                width = int(window.width)
                aoi_block = grid.aoi_mask[row : row + height, col : col + width]

                nbr_blocks = [_read_float_block(dataset, window) for dataset in nbr_datasets]
                nbr_median, valid_count = exact_block_median(nbr_blocks)
                nbr_out.write(
                    np.where(np.isfinite(nbr_median) & aoi_block, nbr_median, FLOAT_NODATA).astype(
                        np.float32, copy=False
                    ),
                    1,
                    window=window,
                )
                count_out.write(
                    np.where(aoi_block, valid_count, COUNT_NODATA).astype(np.uint16, copy=False),
                    1,
                    window=window,
                )
                del nbr_blocks, nbr_median, valid_count

                ndvi_blocks = [_read_float_block(dataset, window) for dataset in ndvi_datasets]
                ndvi_median, _ = exact_block_median(ndvi_blocks)
                ndvi_out.write(
                    np.where(
                        np.isfinite(ndvi_median) & aoi_block, ndvi_median, FLOAT_NODATA
                    ).astype(np.float32, copy=False),
                    1,
                    window=window,
                )
                del ndvi_blocks, ndvi_median
                block_count += 1
                if block_count == 1 or block_count % 16 == 0:
                    telemetry.record(f"during block reduction {block_count}")
        finally:
            for dataset in nbr_datasets + ndvi_datasets:
                dataset.close()
    telemetry.record("after block reduction")
    return {"block_count": block_count, "block_size": BLOCK_SIZE}


def _raster_values(path: Path, grid: AnalysisGrid, *, count: bool = False) -> np.ndarray:
    with rasterio.open(path) as dataset:
        validate_output_grid(dataset, grid, path)
        values = dataset.read(1)
        if count:
            return values.astype(np.uint16, copy=False)
        values = values.astype(np.float32, copy=False)
        if dataset.nodata is not None:
            values[values == dataset.nodata] = np.nan
        values[~np.isfinite(values)] = np.nan
        return values


def _qa_title(year: int) -> str:
    return f"{year} August median NBR"


def _qa_nbr(path: Path, values: np.ndarray, grid: AnalysisGrid, year: int) -> None:
    masked = np.ma.masked_invalid(values)
    colormap = plt.get_cmap("YlGn").copy()
    colormap.set_bad("#d9d9d9")
    finite = masked.compressed()
    upper = max(1.0, float(np.percentile(finite, 99)) if finite.size else 1.0)
    figure, axis = plt.subplots(figsize=(8, 5.5), constrained_layout=True)
    try:
        image = axis.imshow(
            masked,
            origin="upper",
            extent=grid.bounds,
            cmap=colormap,
            norm=Normalize(vmin=-0.5, vmax=upper),
        )
        left, bottom, right, top = grid.bounds
        axis.plot(
            [left, right, right, left, left],
            [bottom, bottom, top, top, bottom],
            color="black",
            linewidth=0.6,
        )
        axis.set_title(_qa_title(year))
        axis.set_xlabel("Easting (m), EPSG:32633")
        axis.set_ylabel("Northing (m), EPSG:32633")
        axis.grid(color="white", linewidth=0.35, alpha=0.35)
        figure.colorbar(image, ax=axis, label="NBR", shrink=0.86)
        figure.savefig(path, dpi=120)
    finally:
        plt.close(figure)


def _build_interval(config: ProjectConfig, year: int) -> tuple[date, date]:
    if year not in config.analysis_years:
        raise ValueError(f"unsupported year {year}; configured years are {config.analysis_years}")
    if (config.month, config.window_start_day, config.window_end_day) != (8, 1, 31):
        raise ValueError(
            "annual compositing requires the configured interval "
            "August 1 through August 31"
        )
    return date(year, 8, 1), date(year, 8, 31)


def _item_date(item: dict[str, Any]) -> date:
    value = item.get("datetime")
    if not value:
        raise ValueError(f"Item {item.get('id')} has no datetime")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build(
    config_path: Path,
    inventory_path: Path,
    output_root: Path,
    temp_root: Path,
    year: int,
    *,
    keep_temp_on_error: bool = False,
    treatment: ReflectanceTreatment | str = ReflectanceTreatment.REJECT,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Build exactly one configured year and return its annual summary."""
    treatment = normalize_reflectance_treatment(treatment)
    telemetry = MemoryTelemetry()
    telemetry.record("build start")
    config = load_config(config_path)
    start_date, end_date = _build_interval(config, year)
    inventory = load_inventory(inventory_path)
    selected = sorted(
        [
            item
            for item in inventory
            if item.get("year") == year and start_date <= _item_date(item) <= end_date
        ],
        key=lambda item: (str(item.get("datetime") or ""), str(item["id"])),
    )
    grid = _approved_grid(config)
    telemetry.record("after STAC discovery/grouping")
    groups = group_acquisition_items(selected)
    processable_by_date = {
        acquisition_date: [item for item in date_items if _processable(item)]
        for acquisition_date, date_items in groups.items()
    }
    print(
        f"{year}: {len(selected)} STAC items in {len(groups)} acquisition groups; "
        f"processing one year sequentially",
        flush=True,
    )

    output_dir = output_root / str(year) if output_dir is None else output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=".annual-staging-", dir=output_dir))
    final_paths = {
        "nbr": output_dir / "nbr.tif",
        "ndvi": output_dir / "ndvi.tif",
        "valid_count": output_dir / "valid_count.tif",
        "qa": output_dir / "nbr-qa.png",
        "summary": output_dir / "annual-summary.json",
    }
    staged_paths = {name: staging_dir / path.name for name, path in final_paths.items()}
    last_date: str | None = None
    peak_temp_bytes = 0

    try:
        with rasterio.Env(
            GDAL_CACHEMAX=256,
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_USE_HEAD="NO",
            GDAL_HTTP_TIMEOUT="60",
            GDAL_HTTP_MAX_RETRY="2",
            GDAL_HTTP_RETRY_DELAY="1",
        ):
            with temporary_workspace(
                temp_root / str(year), year, keep_on_error=keep_temp_on_error
            ) as workspace:
                acquisitions: list[TemporaryAcquisition] = []
                acquisition_records: list[dict[str, Any]] = []
                for acquisition_date in sorted(groups):
                    last_date = acquisition_date
                    if not processable_by_date[acquisition_date]:
                        record = {
                            "date": acquisition_date,
                            "item_ids": [item["id"] for item in groups[acquisition_date]],
                            "acquisition_datetimes": [
                                item.get("datetime") for item in groups[acquisition_date]
                            ],
                            "mgrs_tiles": sorted(
                                {str(item.get("mgrs_tile")) for item in groups[acquisition_date]}
                            ),
                            "scene_cloud_cover": [
                                item.get("eo:cloud_cover") for item in groups[acquisition_date]
                            ],
                            "valid_pixel_count": 0,
                            "valid_pixel_percentage": 0.0,
                            "ndvi_valid_pixel_count": 0,
                            "ndvi_valid_pixel_percentage": 0.0,
                            "mosaic_rule": "no processable HTTPS COG item",
                        }
                    else:
                        acquisition, record = _process_acquisition(
                            acquisition_date,
                            processable_by_date[acquisition_date],
                            grid,
                            workspace,
                            telemetry,
                            treatment,
                        )
                        if acquisition is not None:
                            acquisitions.append(acquisition)
                            peak_temp_bytes = max(peak_temp_bytes, _directory_size(workspace))
                    acquisition_records.append(record)

                telemetry.record("before annual block-wise reduction")
                reduction = _write_block_outputs(
                    acquisitions,
                    grid,
                    staged_paths["nbr"],
                    staged_paths["ndvi"],
                    staged_paths["valid_count"],
                    telemetry,
                )
                peak_temp_bytes = max(peak_temp_bytes, _directory_size(workspace))

        # Final raster QA and distributions are deliberately one raster at a
        # time, after block reduction has completed.
        nbr_values = _raster_values(staged_paths["nbr"], grid)
        nbr_stats = distribution(nbr_values)
        _qa_nbr(staged_paths["qa"], nbr_values, grid, year)
        del nbr_values
        ndvi_values = _raster_values(staged_paths["ndvi"], grid)
        ndvi_stats = distribution(ndvi_values)
        del ndvi_values
        valid_counts = _raster_values(staged_paths["valid_count"], grid, count=True)
        count_stats = valid_count_distribution(valid_counts, grid.aoi_mask)
        del valid_counts
        telemetry.record("after reduction and QA")

        processable_items = [item for item in selected if _processable(item)]
        usable_records = [
            record for record in acquisition_records if is_usable_acquisition(record)
        ]
        aoi_pixels = int(np.count_nonzero(grid.aoi_mask))
        summary: dict[str, Any] = {
            "processing_version": "annual-composite-v1",
            "year": year,
            "requested_interval": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "stac_item_count": len(selected),
            "grouped_acquisition_count": len(groups),
            "usable_acquisition_count": len(usable_records),
            "processable_item_count": len(processable_items),
            "item_ids": [item["id"] for item in selected],
            "mgrs_tiles": sorted({str(item.get("mgrs_tile")) for item in selected}),
            "acquisition_groups": acquisition_records,
            "analysis_grid": {
                "crs": grid.crs,
                "resolution_m": grid.resolution,
                "bounds": list(grid.bounds),
                "width": grid.width,
                "height": grid.height,
                "transform": list(grid.transform),
                "aoi_pixel_count": aoi_pixels,
            },
            "valid_coverage": {
                "nbr_percent": 100.0 * nbr_stats["count"] / aoi_pixels if aoi_pixels else 0.0,
                "ndvi_percent": 100.0 * ndvi_stats["count"] / aoi_pixels if aoi_pixels else 0.0,
            },
            "valid_count_distribution": count_stats,
            "nbr_distribution": nbr_stats,
            "ndvi_distribution": ndvi_stats,
            # Some inventory items can be present but lack one of the required
            # likely-COG assets.  They are intentionally excluded from
            # processing and from the metadata summary as well.
            "reflectance_scale_offset_metadata_encountered": _scale_offset_summary(
                processable_items
            ),
            "processing": {
                "reflectance_treatment": treatment.value,
                "same_date_mosaic": "first valid pixel in sorted (MGRS tile, Item ID) order",
                "scl_invalid_classes": [0, 1, 3, 8, 9, 10, 11],
                "reflectance_resampling": "average",
                "scl_resampling": "nearest-neighbour",
                "temporal_statistic": "exact per-pixel median across valid acquisition dates",
                "block_size": [BLOCK_SIZE, BLOCK_SIZE],
                "concurrency": "sequential acquisition dates, items, and bands",
                "gdal_cache_max_mib": 256,
                "full_sentinel_scene_download": False,
                "permanent_raw_imagery_cache": False,
                "maximum_simultaneous_full_grid_arrays_estimate": (
                    "3 float32 reflectance arrays plus 2 float32 derived-index arrays and "
                    "a bounded number of uint8/bool masks while one item is calculated; "
                    "no full-grid acquisition-date stack"
                ),
            },
            "temporary_storage": {
                "root": str(temp_root / str(year)),
                "format": "AOI-only temporary float32 GeoTIFFs, two per usable acquisition date",
                "peak_bytes": peak_temp_bytes,
                "peak_mib": round(peak_temp_bytes / (1024 * 1024), 3),
                "cleanup_expected": True,
            },
            "memory_telemetry": {
                "events": telemetry.events,
                "peak_max_rss_mib": round(telemetry.peak_mib, 2),
            },
            "reduction": reduction,
            "outputs": {
                "files": {name: str(path) for name, path in final_paths.items()},
                "file_sizes_bytes": {},
            },
        }
        telemetry.record("build end")
        _write_json(staged_paths["summary"], summary)
        for name, path in staged_paths.items():
            if name != "summary":
                os.replace(path, final_paths[name])
        # Write the summary after raster/QA finalization so its file-size map
        # describes the actual final outputs.  Stabilize its own size after
        # each rewrite; in practice this converges in one pass.
        for name, path in final_paths.items():
            if name != "summary":
                summary["outputs"]["file_sizes_bytes"][path.name] = path.stat().st_size
        for _ in range(3):
            _write_json(staged_paths["summary"], summary)
            os.replace(staged_paths["summary"], final_paths["summary"])
            summary_size = final_paths["summary"].stat().st_size
            if (
                summary["outputs"]["file_sizes_bytes"].get(final_paths["summary"].name)
                == summary_size
            ):
                break
            summary["outputs"]["file_sizes_bytes"][final_paths["summary"].name] = summary_size
        return summary
    except Exception as exc:
        last_memory = telemetry.events[-1]["max_rss_mib"] if telemetry.events else None
        print(
            f"Annual build failed for {year} at acquisition date "
            f"{last_date or 'before acquisition'}; "
            f"last observed max RSS={last_memory} MiB: {type(exc).__name__}: {exc}",
            flush=True,
        )
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True, help="one explicit configured year")
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--inventory", type=Path, default=Path("data/inventory/stac-items.json"))
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/annual"))
    parser.add_argument("--temp-root", type=Path, default=Path("data/.tmp/annual"))
    parser.add_argument(
        "--keep-temp-on-error",
        action="store_true",
        help="retain this run's temporary workspace after a failed build for diagnosis",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    summary = build(
        args.config,
        args.inventory,
        args.output_root,
        args.temp_root,
        args.year,
        keep_temp_on_error=args.keep_temp_on_error,
    )
    print(
        f"Wrote {args.year} annual NBR/NDVI outputs; "
        f"peak max RSS={summary['memory_telemetry']['peak_max_rss_mib']:.2f} MiB",
        flush=True,
    )


if __name__ == "__main__":
    main()
