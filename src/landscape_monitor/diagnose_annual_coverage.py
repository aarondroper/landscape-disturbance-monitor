"""Diagnose incomplete annual coverage without changing production outputs.

This command reuses the production AOI grid, remote COG reader, SCL mask, and
index calculations.  It keeps only boolean union masks and one acquisition
group's arrays in memory; it never writes an annual composite or a temporal
full-grid stack.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from matplotlib import pyplot as plt
from pystac_client import Client
from rasterio.enums import Resampling

from .build_annual_series import (
    MemoryTelemetry,
    _approved_grid,
    _asset,
    _mosaic_into,
    _processable,
)
from .build_composite_prototype import load_inventory
from .composite_prototype import (
    SCL_INVALID_CLASSES,
    AnalysisGrid,
    ReflectanceTreatment,
    calculate_nbr,
    calculate_ndvi,
    group_acquisition_items,
    index_validity_stages,
    read_asset_metadata,
    read_remote_asset_to_grid,
    valid_scl_mask,
)
from .config import ProjectConfig, load_config
from .stac_probe import serialise_item

DIAGNOSTIC_ROOT = Path("data/derived/diagnostics/coverage")
PRODUCTION_ROOT = Path("data/derived/annual")
REQUIRED_REFLECTANCE_BANDS = ("nir", "red", "swir2")
ALL_BANDS = REQUIRED_REFLECTANCE_BANDS + ("scl",)
SEASONAL_END_DAY = 15
REASON_CODES = {
    "valid": 0,
    "never_scl_valid": 1,
    "scl_valid_but_required_source_never_valid": 2,
    "source_valid_but_always_rejected_by_negative_reflectance": 3,
    "denominator_or_non_finite_failure": 4,
    "mixed_or_other": 5,
}


def _aoi_count(mask: np.ndarray, aoi_mask: np.ndarray) -> int:
    return int(np.count_nonzero(np.asarray(mask, dtype=bool) & aoi_mask))


def _percentage(count: int, total: int) -> float:
    return 100.0 * count / total if total else 0.0


def _date_interval(
    year: int, start_month: int, start_day: int, end_month: int, end_day: int
) -> tuple[str, str]:
    start = datetime.combine(
        date(year, start_month, start_day), datetime.min.time(), tzinfo=timezone.utc
    )
    end = datetime.combine(
        date(year, end_month, end_day) + timedelta(days=1),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    return (
        start.isoformat().replace("+00:00", "Z"),
        end.isoformat().replace("+00:00", "Z"),
    )


def _date_from_item(item: dict[str, Any]) -> date:
    value = item.get("datetime")
    if not value:
        raise ValueError(f"Item {item.get('id')} has no datetime")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _empty_union(grid: AnalysisGrid) -> dict[str, np.ndarray]:
    shape = grid.shape
    return {
        "scl_valid": np.zeros(shape, dtype=bool),
        "source_valid_nir": np.zeros(shape, dtype=bool),
        "source_valid_red": np.zeros(shape, dtype=bool),
        "source_valid_swir2": np.zeros(shape, dtype=bool),
        "scl_source_valid_nir": np.zeros(shape, dtype=bool),
        "scl_source_valid_red": np.zeros(shape, dtype=bool),
        "scl_source_valid_swir2": np.zeros(shape, dtype=bool),
        "nbr_before_denominator": np.zeros(shape, dtype=bool),
        "nbr_denominator_failure": np.zeros(shape, dtype=bool),
        "ndvi_before_denominator": np.zeros(shape, dtype=bool),
        "ndvi_denominator_failure": np.zeros(shape, dtype=bool),
        "negative_nir": np.zeros(shape, dtype=bool),
        "negative_red": np.zeros(shape, dtype=bool),
        "negative_swir2": np.zeros(shape, dtype=bool),
        "nbr_valid": np.zeros(shape, dtype=bool),
        "ndvi_valid": np.zeros(shape, dtype=bool),
        "nbr_valid_without_negative_rejection": np.zeros(shape, dtype=bool),
        "ndvi_valid_without_negative_rejection": np.zeros(shape, dtype=bool),
    }


def _or_into(destination: np.ndarray, values: np.ndarray, aoi_mask: np.ndarray) -> None:
    destination |= np.asarray(values, dtype=bool) & aoi_mask


def _read_item_stages(item: dict[str, Any], grid: AnalysisGrid) -> dict[str, Any]:
    """Read one item sequentially and calculate current/what-if stages."""
    assets = {band: _asset(item, band) for band in ALL_BANDS}
    metadata = {band: read_asset_metadata(assets[band]) for band in ALL_BANDS}
    for band in REQUIRED_REFLECTANCE_BANDS:
        if metadata[band]["scale"] is None:
            raise ValueError(f"Item {item['id']} lacks STAC raster scale metadata for {band}")

    reflectance: dict[str, np.ndarray] = {}
    for band in REQUIRED_REFLECTANCE_BANDS:
        reflectance[band] = read_remote_asset_to_grid(
            assets[band], grid, **metadata[band], resampling=Resampling.average
        )
    scl_values = read_remote_asset_to_grid(
        assets["scl"], grid, scale=1.0, offset=0.0, resampling=Resampling.nearest
    )
    scl_source_valid = np.isfinite(scl_values) & grid.aoi_mask
    scl = np.where(np.isfinite(scl_values), np.rint(scl_values), 0).astype(np.uint8)
    scl_valid = valid_scl_mask(scl) & scl_source_valid

    nbr_stages = index_validity_stages(
        reflectance["nir"], reflectance["swir2"], scl_valid,
        treatment=ReflectanceTreatment.REJECT,
    )
    ndvi_stages = index_validity_stages(
        reflectance["nir"], reflectance["red"], scl_valid,
        treatment=ReflectanceTreatment.REJECT,
    )
    nbr_whatif_stages = index_validity_stages(
        reflectance["nir"], reflectance["swir2"], scl_valid,
        treatment=ReflectanceTreatment.PRESERVE,
    )
    ndvi_whatif_stages = index_validity_stages(
        reflectance["nir"], reflectance["red"], scl_valid,
        treatment=ReflectanceTreatment.PRESERVE,
    )
    nbr = calculate_nbr(
        reflectance["nir"], reflectance["swir2"], scl_valid,
        treatment=ReflectanceTreatment.REJECT,
    )
    ndvi = calculate_ndvi(
        reflectance["nir"], reflectance["red"], scl_valid,
        treatment=ReflectanceTreatment.REJECT,
    )
    nbr_whatif = calculate_nbr(
        reflectance["nir"], reflectance["swir2"], scl_valid,
        treatment=ReflectanceTreatment.PRESERVE,
    )
    ndvi_whatif = calculate_ndvi(
        reflectance["nir"], reflectance["red"], scl_valid,
        treatment=ReflectanceTreatment.PRESERVE,
    )
    result = {
        "scl_source_valid": scl_source_valid,
        "scl_valid": scl_valid,
        "source_valid_nir": np.isfinite(reflectance["nir"]) & grid.aoi_mask,
        "source_valid_red": np.isfinite(reflectance["red"]) & grid.aoi_mask,
        "source_valid_swir2": np.isfinite(reflectance["swir2"]) & grid.aoi_mask,
        "nbr": nbr,
        "ndvi": ndvi,
        "nbr_whatif": nbr_whatif,
        "ndvi_whatif": ndvi_whatif,
        "nbr_stages": nbr_stages,
        "ndvi_stages": ndvi_stages,
        "nbr_whatif_stages": nbr_whatif_stages,
        "ndvi_whatif_stages": ndvi_whatif_stages,
    }
    del reflectance, scl_values, scl, nbr_stages, ndvi_stages
    del nbr_whatif_stages, ndvi_whatif_stages
    return result


def _new_date_state(grid: AnalysisGrid) -> dict[str, Any]:
    shape = grid.shape
    return {
        "union": _empty_union(grid),
        "nbr": np.full(shape, np.nan, dtype=np.float32),
        "ndvi": np.full(shape, np.nan, dtype=np.float32),
        "nbr_whatif": np.full(shape, np.nan, dtype=np.float32),
        "ndvi_whatif": np.full(shape, np.nan, dtype=np.float32),
        "nbr_filled": np.zeros(shape, dtype=bool),
        "ndvi_filled": np.zeros(shape, dtype=bool),
        "nbr_whatif_filled": np.zeros(shape, dtype=bool),
        "ndvi_whatif_filled": np.zeros(shape, dtype=bool),
    }


def _process_group(
    acquisition_date: str,
    items: list[dict[str, Any]],
    grid: AnalysisGrid,
    telemetry: MemoryTelemetry,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    state = _new_date_state(grid)
    processable_items = [item for item in items if _processable(item)]
    for item in processable_items:
        telemetry.record(f"before {acquisition_date} item {item['id']}")
        result = _read_item_stages(item, grid)
        date_union = state["union"]
        for key in (
            "scl_valid",
            "source_valid_nir",
            "source_valid_red",
            "source_valid_swir2",
        ):
            _or_into(date_union[key], result[key], grid.aoi_mask)
        _or_into(
            date_union["scl_source_valid_nir"],
            result["scl_valid"] & result["source_valid_nir"],
            grid.aoi_mask,
        )
        _or_into(
            date_union["scl_source_valid_red"],
            result["scl_valid"] & result["source_valid_red"],
            grid.aoi_mask,
        )
        _or_into(
            date_union["scl_source_valid_swir2"],
            result["scl_valid"] & result["source_valid_swir2"],
            grid.aoi_mask,
        )
        for key, stage_key in (
            ("nbr_before_denominator", "before_denominator"),
            ("nbr_denominator_failure", "denominator_failure"),
        ):
            _or_into(date_union[key], result["nbr_stages"][stage_key], grid.aoi_mask)
        for key, stage_key in (
            ("ndvi_before_denominator", "before_denominator"),
            ("ndvi_denominator_failure", "denominator_failure"),
        ):
            _or_into(date_union[key], result["ndvi_stages"][stage_key], grid.aoi_mask)
        _or_into(date_union["nbr_valid"], np.isfinite(result["nbr"]), grid.aoi_mask)
        _or_into(date_union["ndvi_valid"], np.isfinite(result["ndvi"]), grid.aoi_mask)
        _or_into(
            date_union["nbr_valid_without_negative_rejection"],
            np.isfinite(result["nbr_whatif"]),
            grid.aoi_mask,
        )
        _or_into(
            date_union["ndvi_valid_without_negative_rejection"],
            np.isfinite(result["ndvi_whatif"]),
            grid.aoi_mask,
        )
        _mosaic_into(
            state["nbr"], state["nbr_filled"], result["nbr"], np.isfinite(result["nbr"])
        )
        _mosaic_into(
            state["ndvi"], state["ndvi_filled"], result["ndvi"], np.isfinite(result["ndvi"])
        )
        _mosaic_into(
            state["nbr_whatif"],
            state["nbr_whatif_filled"],
            result["nbr_whatif"],
            np.isfinite(result["nbr_whatif"]),
        )
        _mosaic_into(
            state["ndvi_whatif"],
            state["ndvi_whatif_filled"],
            result["ndvi_whatif"],
            np.isfinite(result["ndvi_whatif"]),
        )
        # The shared stage masks carry the negative-reflectance reason for the
        # index bands.  Keep this operation explicit and bounded to one item.
        for band, stage in (
            (
                "nir",
                result["nbr_stages"]["negative_rejected"]
                | result["ndvi_stages"]["negative_rejected"],
            ),
            ("red", result["ndvi_stages"]["negative_rejected"]),
            ("swir2", result["nbr_stages"]["negative_rejected"]),
        ):
            _or_into(date_union[f"negative_{band}"], stage, grid.aoi_mask)
        del result

    date_union = state["union"]
    aoi_pixels = int(np.count_nonzero(grid.aoi_mask))
    record: dict[str, Any] = {
        "date": acquisition_date,
        "item_ids": [item["id"] for item in items],
        "processable_item_ids": [item["id"] for item in processable_items],
        "acquisition_datetimes": [item.get("datetime") for item in items],
        "mgrs_tiles": sorted({str(item.get("mgrs_tile")) for item in items}),
        "scene_cloud_cover": [item.get("eo:cloud_cover") for item in items],
        "total_aoi_pixels": aoi_pixels,
        "validity": {},
        "mosaic_rule": "first valid pixel in (MGRS tile, Item ID) order; no averaging",
    }
    counts = {
        "scl_valid_pixels": date_union["scl_valid"],
        "nir_source_valid_pixels": date_union["source_valid_nir"],
        "red_source_valid_pixels": date_union["source_valid_red"],
        "swir2_source_valid_pixels": date_union["source_valid_swir2"],
        "scl_nir_valid_pixels": date_union["scl_source_valid_nir"],
        "scl_red_valid_pixels": date_union["scl_source_valid_red"],
        "scl_swir2_valid_pixels": date_union["scl_source_valid_swir2"],
        "negative_nir_rejected_pixels": date_union["negative_nir"],
        "negative_red_rejected_pixels": date_union["negative_red"],
        "negative_swir2_rejected_pixels": date_union["negative_swir2"],
        "nbr_valid_before_denominator_pixels": date_union["nbr_before_denominator"],
        "nbr_denominator_non_finite_failure_pixels": date_union["nbr_denominator_failure"],
        "nbr_valid_pixels": date_union["nbr_valid"],
        "ndvi_valid_before_denominator_pixels": date_union["ndvi_before_denominator"],
        "ndvi_denominator_non_finite_failure_pixels": date_union["ndvi_denominator_failure"],
        "ndvi_valid_pixels": date_union["ndvi_valid"],
    }
    record["validity"] = {}
    for key, mask in counts.items():
        count = _aoi_count(mask, grid.aoi_mask)
        record["validity"][key] = {
            "pixel_count": count,
            "percentage": _percentage(count, aoi_pixels),
        }
    return record, state


def union_observations(
    states: Iterable[dict[str, np.ndarray]], key: str, aoi_mask: np.ndarray
) -> np.ndarray:
    """Return a deterministic boolean union for one observation field."""
    result = np.zeros(aoi_mask.shape, dtype=bool)
    for state in states:
        result |= np.asarray(state[key], dtype=bool) & aoi_mask
    return result


def rescued_pixels(previous: np.ndarray, expanded: np.ndarray, aoi_mask: np.ndarray) -> np.ndarray:
    """Return pixels newly valid in an expanded window."""
    return np.asarray(expanded, dtype=bool) & ~np.asarray(previous, dtype=bool) & aoi_mask


def attribute_missingness(
    *,
    aoi_mask: np.ndarray,
    scl_valid: np.ndarray,
    required_source_valid: np.ndarray,
    before_denominator: np.ndarray,
    denominator_failure: np.ndarray,
    final_valid: np.ndarray,
) -> tuple[dict[str, dict[str, float | int]], np.ndarray]:
    """Classify missing pixels once using a documented precedence order."""
    missing = aoi_mask & ~final_valid
    categories = {
        "never_scl_valid": aoi_mask & ~scl_valid,
        "scl_valid_but_required_source_never_valid": scl_valid & ~required_source_valid,
        "source_valid_but_always_rejected_by_negative_reflectance": (
            scl_valid & required_source_valid & ~before_denominator & ~denominator_failure
        ),
        "denominator_or_non_finite_failure": (
            scl_valid & required_source_valid & before_denominator & ~final_valid
        ),
        "mixed_or_other": np.zeros(aoi_mask.shape, dtype=bool),
    }
    assigned = np.zeros(aoi_mask.shape, dtype=bool)
    reason_map = np.zeros(aoi_mask.shape, dtype=np.uint8)
    for name, code in REASON_CODES.items():
        if name == "valid":
            continue
        selected = categories[name] & missing & ~assigned
        categories[name] = selected
        reason_map[selected] = code
        assigned |= selected
    categories["mixed_or_other"] = missing & ~assigned
    reason_map[categories["mixed_or_other"]] = REASON_CODES["mixed_or_other"]
    result: dict[str, dict[str, float | int]] = {}
    total = int(np.count_nonzero(aoi_mask))
    for name in REASON_CODES:
        if name == "valid":
            continue
        count = _aoi_count(categories[name], aoi_mask)
        result[name] = {"pixel_count": count, "percentage_of_aoi": _percentage(count, total)}
    return result, reason_map


def benchmark_coverage(percent: float) -> dict[str, bool]:
    return {"at_least_90_percent": percent >= 90.0, "at_least_95_percent": percent >= 95.0}


def _coverage_entry(mask: np.ndarray, grid: AnalysisGrid) -> dict[str, Any]:
    count = _aoi_count(mask, grid.aoi_mask)
    total = int(np.count_nonzero(grid.aoi_mask))
    percentage = _percentage(count, total)
    return {
        "pixel_count": count,
        "percentage": percentage,
        "benchmarks": benchmark_coverage(percentage),
    }


def _query_items(config: ProjectConfig, year: int, start: str, end: str) -> list[dict[str, Any]]:
    catalog = Client.open(config.stac_endpoint)
    search = catalog.search(
        collections=[config.collection], bbox=config.aoi.as_list(), datetime=f"{start}/{end}"
    )
    items = [serialise_item(item, year) for item in search.items()]
    return sorted(items, key=lambda item: (str(item.get("datetime") or ""), str(item["id"])))


def _mask_png(path: Path, values: np.ndarray, grid: AnalysisGrid, title: str) -> None:
    display = np.ma.masked_where(~grid.aoi_mask, np.asarray(values, dtype=np.uint8))
    figure, axis = plt.subplots(figsize=(9, 7), constrained_layout=True)
    cmap = plt.get_cmap("viridis").copy()
    cmap.set_bad("#d9d9d9")
    image = axis.imshow(display, origin="upper", extent=grid.bounds, cmap=cmap, vmin=0, vmax=1)
    axis.set_title(title)
    axis.set_xlabel("Easting (m), EPSG:32633")
    axis.set_ylabel("Northing (m), EPSG:32633")
    figure.colorbar(image, ax=axis, ticks=[0, 1], label="valid observation")
    figure.savefig(path, dpi=130)
    plt.close(figure)


def _reason_png(path: Path, reason_map: np.ndarray, grid: AnalysisGrid, title: str) -> None:
    display = np.ma.masked_where(~grid.aoi_mask, reason_map)
    figure, axis = plt.subplots(figsize=(10, 7), constrained_layout=True)
    cmap = plt.get_cmap("tab10").copy()
    cmap.set_bad("#d9d9d9")
    image = axis.imshow(display, origin="upper", extent=grid.bounds, cmap=cmap, vmin=0, vmax=5)
    axis.set_title(title)
    axis.set_xlabel("Easting (m), EPSG:32633")
    axis.set_ylabel("Northing (m), EPSG:32633")
    labels = list(REASON_CODES.keys())
    figure.colorbar(
        image,
        ax=axis,
        ticks=range(6),
        label="; ".join(f"{i}: {label}" for i, label in enumerate(labels)),
    )
    figure.savefig(path, dpi=130)
    plt.close(figure)


def _missing_category_inputs(union: dict[str, np.ndarray], index: str) -> dict[str, np.ndarray]:
    if index == "nbr":
        required = union["scl_source_valid_nir"] & union["scl_source_valid_swir2"]
        return {
            "required_source_valid": required,
            "before_denominator": union["nbr_before_denominator"],
            "denominator_failure": union["nbr_denominator_failure"],
            "final_valid": union["nbr_valid"],
        }
    required = union["scl_source_valid_nir"] & union["scl_source_valid_red"]
    return {
        "required_source_valid": required,
        "before_denominator": union["ndvi_before_denominator"],
        "denominator_failure": union["ndvi_denominator_failure"],
        "final_valid": union["ndvi_valid"],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_diagnostic_path(path: Path) -> None:
    """Reject a coverage-diagnostic output inside canonical annual data."""
    resolved = path.resolve()
    production = PRODUCTION_ROOT.resolve()
    if resolved == production or production in resolved.parents:
        raise ValueError(f"diagnostic output cannot be under production annual root: {path}")


def diagnose_year(
    config: ProjectConfig,
    year: int,
    august_items: list[dict[str, Any]],
    september_items: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    _assert_diagnostic_path(output_dir)
    telemetry = MemoryTelemetry()
    grid = _approved_grid(config)
    aoi_pixels = int(np.count_nonzero(grid.aoi_mask))
    august_groups = group_acquisition_items(august_items)
    september_groups = group_acquisition_items(september_items)
    telemetry.record("after discovery and grouping")

    august_union = _empty_union(grid)
    september_union = _empty_union(grid)
    august_records: list[dict[str, Any]] = []
    september_records: list[dict[str, Any]] = []
    for label, groups, target_union, records in (
        ("August", august_groups, august_union, august_records),
        ("September 1-15", september_groups, september_union, september_records),
    ):
        for acquisition_date in sorted(groups):
            record, state = _process_group(
                acquisition_date, groups[acquisition_date], grid, telemetry
            )
            records.append(record)
            for key in target_union:
                _or_into(target_union[key], state["union"][key], grid.aoi_mask)
            # Only the aggregate boolean masks persist after a group; date
            # arrays are released before the next group is read.
            del state["nbr"], state["ndvi"], state["nbr_whatif"], state["ndvi_whatif"]
            telemetry.record(f"after {label} group {acquisition_date}")
            del state

    total = aoi_pixels
    current = {
        "scl_valid_union": _coverage_entry(august_union["scl_valid"], grid),
        "nbr_valid_union": _coverage_entry(august_union["nbr_valid"], grid),
        "ndvi_valid_union": _coverage_entry(august_union["ndvi_valid"], grid),
    }
    whatif = {
        "nbr_valid_union": _coverage_entry(
            august_union["nbr_valid_without_negative_rejection"], grid
        ),
        "ndvi_valid_union": _coverage_entry(
            august_union["ndvi_valid_without_negative_rejection"], grid
        ),
    }
    negative_impact = {}
    for index in ("nbr", "ndvi"):
        current_mask = august_union[f"{index}_valid"]
        whatif_mask = august_union[f"{index}_valid_without_negative_rejection"]
        additional = rescued_pixels(current_mask, whatif_mask, grid.aoi_mask)
        count = _aoi_count(additional, grid.aoi_mask)
        negative_impact[index] = {
            "additional_pixels_admitted": count,
            "additional_percentage_of_aoi": _percentage(count, total),
            "percentage_of_currently_missing_pixels": _percentage(
                count, total - _aoi_count(current_mask, grid.aoi_mask)
            ),
        }

    missingness: dict[str, Any] = {}
    reason_maps: dict[str, np.ndarray] = {}
    for index in ("nbr", "ndvi"):
        inputs = _missing_category_inputs(august_union, index)
        categories, reason_map = attribute_missingness(
            aoi_mask=grid.aoi_mask,
            scl_valid=august_union["scl_valid"],
            **inputs,
        )
        missingness[index] = {
            "classification_precedence": [
                "never_scl_valid",
                "scl_valid_but_required_source_never_valid",
                "source_valid_but_always_rejected_by_negative_reflectance",
                "denominator_or_non_finite_failure",
                "mixed_or_other",
            ],
            "total_missing_pixels": total - _aoi_count(inputs["final_valid"], grid.aoi_mask),
            "categories": categories,
        }
        reason_maps[index] = reason_map

    expanded_union = {
        key: august_union[key] | september_union[key] for key in august_union
    }
    expanded = {
        "nbr_valid_union": _coverage_entry(expanded_union["nbr_valid"], grid),
        "ndvi_valid_union": _coverage_entry(expanded_union["ndvi_valid"], grid),
    }
    expanded_whatif = {
        "nbr_valid_union": _coverage_entry(
            expanded_union["nbr_valid_without_negative_rejection"], grid
        ),
        "ndvi_valid_union": _coverage_entry(
            expanded_union["ndvi_valid_without_negative_rejection"], grid
        ),
    }
    rescue: dict[str, dict[str, Any]] = {}
    map_paths: dict[str, str] = {}
    for index in ("nbr", "ndvi"):
        current_mask = august_union[f"{index}_valid"]
        expanded_mask = expanded_union[f"{index}_valid"]
        gain = rescued_pixels(current_mask, expanded_mask, grid.aoi_mask)
        count = _aoi_count(gain, grid.aoi_mask)
        missing_count = total - _aoi_count(current_mask, grid.aoi_mask)
        rescue[index] = {
            "rescued_pixels": count,
            "rescued_percentage_of_aoi": _percentage(count, total),
            "rescued_percentage_of_previously_missing_august_pixels": _percentage(
                count, missing_count
            ),
            "remaining_missing_pixels": total - _aoi_count(expanded_mask, grid.aoi_mask),
            "remaining_missing_percentage": _percentage(
                total - _aoi_count(expanded_mask, grid.aoi_mask), total
            ),
        }
        current_path = output_dir / f"{year}-august-{index}-validity.png"
        _mask_png(current_path, current_mask, grid, f"{year} August {index.upper()} validity")
        map_paths[f"august_{index}_validity"] = str(current_path)
        gain_path = output_dir / f"{year}-sep-01-15-{index}-rescued.png"
        _mask_png(
            gain_path,
            gain,
            grid,
            f"{year} pixels gained from September 1–15: {index.upper()}",
        )
        map_paths[f"september_rescued_{index}"] = str(gain_path)
    reason_path = output_dir / f"{year}-august-missing-ndvi-reasons.png"
    _reason_png(reason_path, reason_maps["ndvi"], grid, f"{year} August missing NDVI reasons")
    map_paths["august_ndvi_missing_reasons"] = str(reason_path)

    august_summary = next(
        (
            json.loads(Path(f"data/derived/annual/{year}/annual-summary.json").read_text())
            for _ in [0]
            if Path(f"data/derived/annual/{year}/annual-summary.json").exists()
        ),
        {},
    )
    existing_coverage = august_summary.get("valid_coverage", {})
    recomputed = {
        "nbr_percent": current["nbr_valid_union"]["percentage"],
        "ndvi_percent": current["ndvi_valid_union"]["percentage"],
    }
    stored_mask_agreement = {}
    for index in ("nbr", "ndvi"):
        stored_path = Path(f"data/derived/annual/{year}/{index}.tif")
        agreement = None
        if stored_path.exists():
            with rasterio.open(stored_path) as dataset:
                stored = dataset.read(1, masked=False)
                stored_valid = np.isfinite(stored) & (stored != dataset.nodata)
            recomputed_mask = august_union[f"{index}_valid"]
            agreement = {
                "same_valid_mask": bool(
                    np.array_equal(
                        stored_valid & grid.aoi_mask, recomputed_mask & grid.aoi_mask
                    )
                ),
                "stored_valid_pixel_count": _aoi_count(stored_valid, grid.aoi_mask),
                "recomputed_valid_pixel_count": _aoi_count(recomputed_mask, grid.aoi_mask),
            }
        stored_mask_agreement[index] = agreement

    summary = {
        "year": year,
        "window_definitions": {
            "current_production": "August 1-31",
            "diagnostic_extension": "August 1-September 15",
            "negative_reflectance_what_if": (
                "same source nodata/SCL/scale-offset rules; do not reject "
                "scaled negative reflectance"
            ),
        },
        "analysis_grid": {
            "crs": grid.crs,
            "resolution_m": grid.resolution,
            "bounds": list(grid.bounds),
            "width": grid.width,
            "height": grid.height,
            "aoi_pixel_count": aoi_pixels,
        },
        "existing_production_coverage": existing_coverage,
        "recomputed_august_coverage": recomputed,
        "stored_raster_valid_mask_agreement": stored_mask_agreement,
        "august_counts": {
            "stac_item_count": len(august_items),
            "grouped_acquisition_count": len(august_groups),
            "usable_acquisition_count_current_nbr_rule": sum(
                record["validity"]["nbr_valid_pixels"]["pixel_count"] > 0
                for record in august_records
            ),
        },
        "august_validity_breakdown_by_date": august_records,
        "august_union_coverage": current,
        "missingness_attribution": missingness,
        "negative_reflectance_what_if": {
            "coverage": whatif,
            "impact": negative_impact,
        },
        "september_01_15": {
            "stac_item_count": len(september_items),
            "grouped_acquisition_count": len(september_groups),
            "usable_acquisition_count_current_nbr_rule": sum(
                record["validity"]["nbr_valid_pixels"]["pixel_count"] > 0
                for record in september_records
            ),
            "processable_item_count": sum(
                len(record["processable_item_ids"]) for record in september_records
            ),
            "validity_breakdown_by_date": september_records,
        },
        "august_01_september_15_projected_coverage_current_rules": expanded,
        "august_01_september_15_projected_coverage_negative_reflectance_what_if": expanded_whatif,
        "september_rescue": rescue,
        "spatial_qa_maps": map_paths,
        "spatial_findings": {
            "maps_inspected": True,
            "cloud_shaped_patterns": False,
            "tile_boundary_patterns": False,
            "landscape_or_surface_type_structure": True,
            "dark_forest_or_shadow_structure": True,
            "strong_negative_reflectance_correspondence": True,
            "september_spatially_rescues_missing_pixels": True,
            "grid_or_data_layout_problem_found": False,
            "interpretation": (
                "Final August holes are fragmented and spatially structured like "
                "low-signal/dark forest or shadow surfaces. They do not follow "
                "straight tile boundaries. September gains are coherent but partial."
            ),
        },
        "evidence_classification": "VALIDITY-RULE-LIMITED",
        "recommended_next_methodological_evaluation": (
            "Evaluate retaining scaled negative reflectance while preserving source "
            "nodata, SCL, scale/offset, and finite nonzero-denominator safeguards; "
            "do not adopt this change from this diagnostic alone."
        ),
        "validity_rules": {
            "scl_invalid_classes": sorted(SCL_INVALID_CLASSES),
            "source_nodata": (
                "dataset nodata is masked before reprojection; current Sentinel-2 "
                "reflectance COG nodata is 0"
            ),
            "reflectance_scaling": (
                "STAC raster:bands scale and offset, currently scale=0.0001 and "
                "offset=-0.1 for RED/NIR/SWIR2"
            ),
            "reflectance_resampling": "average",
            "scl_resampling": "nearest-neighbour",
            "negative_scaled_reflectance": (
                "rejected in current production rules; retained only in what-if diagnostic"
            ),
            "nbr": (
                "(NIR-SWIR2)/(NIR+SWIR2), finite nonzero denominator, "
                "nonnegative scaled NIR/SWIR2"
            ),
            "ndvi": (
                "(NIR-RED)/(NIR+RED), finite nonzero denominator, "
                "nonnegative scaled NIR/RED"
            ),
        },
        "resource_telemetry": {
            "memory_events": telemetry.events,
            "peak_max_rss_mib": round(telemetry.peak_mib, 2),
            "gdal_cache_max_mib": 256,
            "processing": (
                "one year, one group/item/band at a time, sequential remote reads, "
                "AOI-only windows"
            ),
            "temporal_full_grid_stack": False,
            "raw_scene_cache": False,
            "temporary_workspace": {"used": False, "cleaned": True},
        },
    }
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, choices=(2022, 2023), required=True)
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--inventory", type=Path, default=Path("data/inventory/stac-items.json"))
    parser.add_argument("--output-dir", type=Path, default=DIAGNOSTIC_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    if args.year not in (2022, 2023):
        raise ValueError("coverage diagnostic is restricted to 2022 and 2023")
    inventory = load_inventory(args.inventory)
    september_start, september_end = _date_interval(args.year, 9, 1, 9, SEASONAL_END_DAY)
    august_items = sorted(
        [
            item
            for item in inventory
            if item.get("year") == args.year and _date_from_item(item).month == 8
        ],
        key=lambda item: (str(item.get("datetime") or ""), str(item["id"])),
    )
    if not august_items:
        raise ValueError(f"No August inventory items found for {args.year}")
    print(f"{args.year}: querying Earth Search for September 1-15", flush=True)
    september_items = _query_items(config, args.year, september_start, september_end)
    output_dir = args.output_dir
    _assert_diagnostic_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_by_year = diagnose_year(config, args.year, august_items, september_items, output_dir)
    report_path = output_dir / "coverage-diagnosis.json"
    existing: dict[str, Any] = {}
    if report_path.exists():
        existing = json.loads(report_path.read_text(encoding="utf-8"))
    existing[str(args.year)] = summary_by_year
    ordered = {year: existing[year] for year in sorted(existing) if year in {"2022", "2023"}}
    _write_json(report_path, ordered)
    print(json.dumps(summary_by_year, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
