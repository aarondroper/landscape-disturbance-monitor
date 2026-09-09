"""Build the August 2017/2018 AOI-only NBR/dNBR prototype."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from matplotlib import pyplot as plt
from matplotlib.colors import Normalize
from rasterio.enums import Resampling

from .composite_prototype import (
    COUNT_NODATA,
    FLOAT_NODATA,
    SCL_INVALID_CLASSES,
    AnalysisGrid,
    area_hectares_at_least,
    calculate_nbr,
    create_analysis_grid,
    distribution,
    dnbr,
    group_acquisition_items,
    median_composite,
    mosaic_valid_pixels,
    read_asset_metadata,
    read_remote_asset_to_grid,
    valid_count_distribution,
    valid_scl_mask,
)
from .config import ProjectConfig, load_config

DIAGNOSTIC_DNBR_THRESHOLDS = (0.10, 0.20, 0.30, 0.40, 0.50)
BASELINE_NBR_THRESHOLDS = (None, 0.20, 0.30, 0.40)
PROCESSING_BANDS = ("nir", "swir2", "scl")


def load_inventory(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        content = json.load(file)
    items = content.get("items")
    if not isinstance(items, list):
        raise ValueError(f"Inventory {path} does not contain an items list")
    return items


def _asset(item: dict[str, Any], band: str) -> dict[str, Any]:
    choices = item.get("relevant_assets", {}).get(band, [])
    candidates = [choice for choice in choices if choice.get("cog_likely")]
    if not candidates:
        raise ValueError(f"Item {item['id']} has no likely COG for {band}")
    return sorted(candidates, key=lambda value: str(value.get("key")))[0]


def _read_item_observation(
    item: dict[str, Any], grid: AnalysisGrid
) -> tuple[np.ndarray, np.ndarray]:
    metadata = {band: read_asset_metadata(_asset(item, band)) for band in ("nir", "swir2", "scl")}
    if metadata["nir"]["scale"] is None or metadata["swir2"]["scale"] is None:
        raise ValueError(
            f"Item {item['id']} lacks STAC raster scale metadata for NIR/SWIR2; "
            "refresh the inventory with stac_probe.py"
        )
    nir = read_remote_asset_to_grid(
        _asset(item, "nir"), grid, **metadata["nir"], resampling=Resampling.average
    )
    swir2 = read_remote_asset_to_grid(
        _asset(item, "swir2"), grid, **metadata["swir2"], resampling=Resampling.average
    )
    scl = read_remote_asset_to_grid(
        _asset(item, "scl"), grid, scale=1.0, offset=0.0, resampling=Resampling.nearest
    )
    scl = np.where(np.isfinite(scl), np.rint(scl), 0).astype(np.uint8)
    mask = valid_scl_mask(scl) & np.isfinite(nir) & np.isfinite(swir2) & grid.aoi_mask
    nbr = calculate_nbr(nir, swir2, mask)
    return nbr, mask & np.isfinite(nbr)


def process_year(items: list[dict[str, Any]], year: int, grid: AnalysisGrid) -> dict[str, Any]:
    groups = group_acquisition_items(items)
    observations: list[np.ndarray] = []
    dates: list[dict[str, Any]] = []
    for acquisition_date, date_items in groups.items():
        for item in date_items:
            print(f"{year} {acquisition_date}: reading {item['id']}", flush=True)
        # Items on one date are independent remote reads.  Collect futures in
        # the already sorted item order so concurrency cannot change the
        # deterministic first-valid mosaic precedence.
        with ThreadPoolExecutor(max_workers=min(4, len(date_items))) as executor:
            futures = [executor.submit(_read_item_observation, item, grid) for item in date_items]
            item_results = [future.result() for future in futures]
        tile_arrays = [result[0] for result in item_results]
        tile_masks = [result[1] for result in item_results]
        date_nbr, date_mask = mosaic_valid_pixels(tile_arrays, tile_masks)
        date_nbr[~grid.aoi_mask] = np.nan
        observations.append(date_nbr)
        dates.append(
            {
                "date": acquisition_date,
                "item_ids": [item["id"] for item in date_items],
                "mgrs_tiles": sorted({str(item.get("mgrs_tile")) for item in date_items}),
                "valid_pixel_count": int(np.count_nonzero(date_mask & grid.aoi_mask)),
                "valid_pixel_percentage": float(
                    100
                    * np.count_nonzero(date_mask & grid.aoi_mask)
                    / np.count_nonzero(grid.aoi_mask)
                ),
                "mosaic_rule": "first valid pixel in (MGRS tile, Item ID) order; no averaging",
            }
        )
    composite, valid_count = median_composite(observations)
    composite[~grid.aoi_mask] = np.nan
    valid_count[~grid.aoi_mask] = 0
    return {
        "year": year,
        "acquisition_dates": dates,
        "input_item_ids": [item["id"] for item in items],
        "nbr_observations": observations,
        "nbr": composite,
        "valid_count": valid_count,
        "valid_count_distribution": valid_count_distribution(valid_count, grid.aoi_mask),
        "acquisition_date_groups": len(dates),
        "usable_acquisition_dates": sum(
            date_record["valid_pixel_count"] > 0 for date_record in dates
        ),
        "composite_valid_pixel_count": int(
            np.count_nonzero(np.isfinite(composite) & grid.aoi_mask)
        ),
        "composite_valid_pixel_percentage": float(
            100
            * np.count_nonzero(np.isfinite(composite) & grid.aoi_mask)
            / np.count_nonzero(grid.aoi_mask)
        ),
    }


def _write_raster(
    path: Path, values: np.ndarray, grid: AnalysisGrid, *, count_raster: bool
) -> None:
    if count_raster:
        output = np.where(grid.aoi_mask, values, COUNT_NODATA).astype(np.uint16)
        dtype = "uint16"
        nodata: int | float = COUNT_NODATA
        predictor = 2
    else:
        output = np.where(np.isfinite(values) & grid.aoi_mask, values, FLOAT_NODATA).astype(
            np.float32
        )
        dtype = "float32"
        nodata = FLOAT_NODATA
        predictor = 3
    profile = {
        "driver": "GTiff",
        "height": grid.height,
        "width": grid.width,
        "count": 1,
        "dtype": dtype,
        "crs": grid.crs,
        "transform": grid.transform,
        "nodata": nodata,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "compress": "deflate",
        "predictor": predictor,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(output, 1)


def _plot_raster(
    path: Path, values: np.ndarray, grid: AnalysisGrid, title: str, cmap: str, *, counts: bool
) -> None:
    masked = np.ma.masked_invalid(np.asarray(values, dtype=np.float32))
    colormap = plt.get_cmap(cmap).copy()
    colormap.set_bad("#d9d9d9")
    finite = masked.compressed()
    if counts:
        vmin, vmax = 0, max(1, int(np.max(finite)) if finite.size else 1)
        norm = Normalize(vmin=vmin, vmax=vmax)
        label = "valid acquisition dates"
    elif title.startswith("dNBR"):
        limit = max(0.5, float(np.percentile(np.abs(finite), 99)) if finite.size else 0.5)
        norm = Normalize(vmin=-limit, vmax=limit)
        label = "dNBR (NBR 2017 − NBR 2018)"
    else:
        norm = Normalize(vmin=-0.5, vmax=1.0)
        label = "NBR"
    figure, axis = plt.subplots(figsize=(10, 7), constrained_layout=True)
    image = axis.imshow(masked, origin="upper", extent=grid.bounds, cmap=colormap, norm=norm)
    left, bottom, right, top = grid.bounds
    axis.plot(
        [left, right, right, left, left],
        [bottom, bottom, top, top, bottom],
        color="black",
        linewidth=0.6,
    )
    axis.set_title(title)
    axis.set_xlabel("Easting (m), EPSG:32633")
    axis.set_ylabel("Northing (m), EPSG:32633")
    axis.grid(color="white", linewidth=0.35, alpha=0.35)
    figure.colorbar(image, ax=axis, label=label, shrink=0.86)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _threshold_diagnostics(dnbr_values: np.ndarray, pre_nbr: np.ndarray) -> dict[str, Any]:
    threshold_results: dict[str, Any] = {}
    for threshold in DIAGNOSTIC_DNBR_THRESHOLDS:
        threshold_results[f"{threshold:.2f}"] = area_hectares_at_least(dnbr_values, threshold)
    baseline_results: dict[str, Any] = {}
    for threshold in BASELINE_NBR_THRESHOLDS:
        label = "none" if threshold is None else f"{threshold:.1f}"
        mask = dnbr_values.copy()
        if threshold is not None:
            mask = np.where(np.isfinite(pre_nbr) & (pre_nbr > threshold), mask, np.nan)
        baseline_results[label] = {
            "baseline_nbr_condition": "none" if threshold is None else f"NBR_2017 > {threshold}",
            "threshold_areas": {
                f"{dnbr_threshold:.2f}": area_hectares_at_least(mask, dnbr_threshold)
                for dnbr_threshold in DIAGNOSTIC_DNBR_THRESHOLDS
            },
        }
    return {"threshold_areas": threshold_results, "baseline_nbr_masks": baseline_results}


def _scale_offset_summary(year_items: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for band in ("nir", "swir2", "scl"):
        pairs = set()
        for item in year_items:
            metadata = read_asset_metadata(_asset(item, band))
            pairs.add((metadata["scale"], metadata["offset"]))
        result[band] = [
            {"scale": scale, "offset": offset} for scale, offset in sorted(pairs, key=str)
        ]
    return result


def build(config_path: Path, inventory_path: Path, output_dir: Path) -> dict[str, Any]:
    config: ProjectConfig = load_config(config_path)
    inventory = load_inventory(inventory_path)
    selected = [item for item in inventory if item.get("year") in (2017, 2018)]
    if len(selected) != 85:
        raise ValueError(f"Expected 85 inventoried 2017/2018 items, found {len(selected)}")
    if any(
        not all(item.get("relevant_assets", {}).get(band) for band in PROCESSING_BANDS)
        for item in selected
    ):
        raise ValueError("Every selected item must have NIR, SWIR2, and SCL assets")
    grid = create_analysis_grid(config.aoi)
    output_dir.mkdir(parents=True, exist_ok=True)
    grouped = {
        year: sorted(
            (item for item in selected if item["year"] == year), key=lambda item: item["id"]
        )
        for year in (2017, 2018)
    }
    year_results = {year: process_year(grouped[year], year, grid) for year in (2017, 2018)}
    pre_nbr = year_results[2017]["nbr"]
    post_nbr = year_results[2018]["nbr"]
    change = dnbr(pre_nbr, post_nbr)
    diagnostics = _threshold_diagnostics(change, pre_nbr)

    _write_raster(output_dir / "nbr_2017.tif", pre_nbr, grid, count_raster=False)
    _write_raster(output_dir / "nbr_2018.tif", post_nbr, grid, count_raster=False)
    _write_raster(output_dir / "dnbr_2017_2018.tif", change, grid, count_raster=False)
    _write_raster(
        output_dir / "valid_count_2017.tif",
        year_results[2017]["valid_count"],
        grid,
        count_raster=True,
    )
    _write_raster(
        output_dir / "valid_count_2018.tif",
        year_results[2018]["valid_count"],
        grid,
        count_raster=True,
    )
    _plot_raster(
        output_dir / "nbr_2017.png", pre_nbr, grid, "August median NBR — 2017", "YlGn", counts=False
    )
    _plot_raster(
        output_dir / "nbr_2018.png",
        post_nbr,
        grid,
        "August median NBR — 2018",
        "YlGn",
        counts=False,
    )
    _plot_raster(
        output_dir / "dnbr_2017_2018.png",
        change,
        grid,
        "August dNBR — 2017 minus 2018",
        "RdBu_r",
        counts=False,
    )
    _plot_raster(
        output_dir / "valid_count_2017.png",
        year_results[2017]["valid_count"],
        grid,
        "Valid acquisition-date count — 2017",
        "viridis",
        counts=True,
    )
    _plot_raster(
        output_dir / "valid_count_2018.png",
        year_results[2018]["valid_count"],
        grid,
        "Valid acquisition-date count — 2018",
        "viridis",
        counts=True,
    )

    all_selected = grouped[2017] + grouped[2018]
    summary = {
        "prototype": "August 2017 pre-disturbance versus August 2018 post-disturbance NBR",
        "aoi": {
            "west": config.aoi.west,
            "south": config.aoi.south,
            "east": config.aoi.east,
            "north": config.aoi.north,
        },
        "analysis_grid": {
            "crs": grid.crs,
            "resolution_m": grid.resolution,
            "bounds": list(grid.bounds),
            "width": grid.width,
            "height": grid.height,
            "transform": list(grid.transform),
            "aoi_pixel_count": int(np.count_nonzero(grid.aoi_mask)),
            "pixel_area_hectares": 0.04,
        },
        "inventory": {
            "path": str(inventory_path),
            "stac_endpoint": config.stac_endpoint,
            "collection": config.collection,
            "source_is_existing_inventory": True,
            "full_scene_download": False,
            "local_raw_cache": False,
        },
        "input_item_ids": {
            str(year): year_results[year]["input_item_ids"] for year in (2017, 2018)
        },
        "acquisition_grouping": {
            "identifier": "UTC calendar date",
            "dates_are_one_observation_each": True,
            "same_date_mosaic_order": "MGRS tile, then Item ID ascending",
            "overlap_rule": "first valid pixel wins; valid overlaps are not averaged",
        },
        "scl_mask": {
            "invalid_classes": sorted(SCL_INVALID_CLASSES),
            "remaining_classes_valid": True,
        },
        "reflectance_scale_offset": {
            "source": "STAC raster:bands metadata preserved in inventory",
            "applied_before_reprojection": True,
            "by_band": _scale_offset_summary(all_selected),
        },
        "years": {
            str(year): {
                "acquisition_date_groups": year_results[year]["acquisition_date_groups"],
                "usable_acquisition_dates": year_results[year]["usable_acquisition_dates"],
                "acquisition_dates": year_results[year]["acquisition_dates"],
                "composite_valid_pixel_count": year_results[year]["composite_valid_pixel_count"],
                "composite_valid_pixel_percentage": year_results[year][
                    "composite_valid_pixel_percentage"
                ],
                "valid_observation_count_distribution": year_results[year][
                    "valid_count_distribution"
                ],
                "nbr_distribution": distribution(year_results[year]["nbr"]),
            }
            for year in (2017, 2018)
        },
        "dnbr": {
            "definition": "NBR_2017 - NBR_2018",
            "distribution": distribution(change),
            **diagnostics,
        },
        "outputs": {
            "rasters": [
                "nbr_2017.tif",
                "nbr_2018.tif",
                "dnbr_2017_2018.tif",
                "valid_count_2017.tif",
                "valid_count_2018.tif",
            ],
            "quicklooks": [
                "nbr_2017.png",
                "nbr_2018.png",
                "dnbr_2017_2018.png",
                "valid_count_2017.png",
                "valid_count_2018.png",
            ],
            "format_note": "AOI-only analytical GeoTIFFs; COG compliance not claimed or validated",
        },
    }
    summary_path = output_dir / "prototype-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--inventory", type=Path, default=Path("data/inventory/stac-items.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/derived/prototype"))
    args = parser.parse_args()
    build(args.config, args.inventory, args.output_dir)
    print(f"Wrote prototype outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
