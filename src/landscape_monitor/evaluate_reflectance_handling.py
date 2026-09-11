"""Evaluate Sentinel-2 negative-reflectance treatments without changing production outputs.

The command builds only diagnostic annual medians for 2022 and 2023.  It uses
the same sequential, AOI-only, disk-backed annual reducer as production and
never writes beneath ``data/derived/annual``.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from matplotlib import pyplot as plt
from matplotlib.colors import Normalize, TwoSlopeNorm

from .build_annual_series import (
    _approved_grid,
    _asset,
    _processable,
    build,
    validate_output_grid,
)
from .build_composite_prototype import load_inventory
from .composite_prototype import (
    AnalysisGrid,
    ReflectanceTreatment,
    index_validity_stages,
    read_item_indices,
)
from .config import load_config

DEFAULT_ROOT = Path("data/derived/diagnostics/reflectance")
PRODUCTION_ROOT = Path("data/derived/annual")
YEARS = (2022, 2023)
INDEX_PAIRS = {
    "nbr": ("nir", "swir2"),
    "ndvi": ("nir", "red"),
}
NEAR_ZERO_THRESHOLDS = (1e-6, 1e-5, 1e-4, 1e-3, 1e-2)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_diagnostic_path(path: Path, root: Path) -> None:
    """Reject a diagnostic output that could resolve into canonical annual data."""
    resolved = path.resolve()
    production = PRODUCTION_ROOT.resolve()
    if resolved == production or production in resolved.parents:
        raise ValueError(f"diagnostic output cannot be under production annual root: {path}")
    if resolved != root.resolve() and root.resolve() not in resolved.parents:
        raise ValueError(f"diagnostic output must be beneath {root}: {path}")


def _finite(values: np.ndarray) -> np.ndarray:
    return np.asarray(values)[np.isfinite(values)]


def _index_distribution(values: np.ndarray) -> dict[str, Any]:
    finite = _finite(values).astype(np.float64, copy=False)
    if not finite.size:
        return {
            "count": 0,
            "min": None,
            "p0.1": None,
            "p1": None,
            "p5": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p95": None,
            "p99": None,
            "p99.9": None,
            "max": None,
            "mean": None,
            "std": None,
        }
    percentiles = np.percentile(finite, [0.1, 1, 5, 25, 50, 75, 95, 99, 99.9])
    names = ("p0.1", "p1", "p5", "p25", "median", "p75", "p95", "p99", "p99.9")
    result: dict[str, Any] = {
        "count": int(finite.size),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "std": float(np.std(finite)),
    }
    result.update({name: float(value) for name, value in zip(names, percentiles, strict=True)})
    return result


def _coverage(values: np.ndarray, aoi_mask: np.ndarray) -> dict[str, Any]:
    total = int(np.count_nonzero(aoi_mask))
    valid = int(np.count_nonzero(np.isfinite(values) & aoi_mask))
    return {
        "valid_pixel_count": valid,
        "aoi_pixel_count": total,
        "valid_percentage": 100.0 * valid / total if total else 0.0,
    }


def _extremes(values: np.ndarray) -> dict[str, Any]:
    finite = np.isfinite(values)
    total = int(np.count_nonzero(finite))
    result: dict[str, Any] = {"valid_pixel_count": total}
    for label, mask in (
        ("less_than_minus_1", finite & (values < -1)),
        ("greater_than_1", finite & (values > 1)),
        ("abs_greater_than_1", finite & (np.abs(values) > 1)),
        ("abs_greater_than_2", finite & (np.abs(values) > 2)),
        ("abs_greater_than_5", finite & (np.abs(values) > 5)),
        ("abs_greater_than_10", finite & (np.abs(values) > 10)),
    ):
        count = int(np.count_nonzero(mask))
        result[label] = {
            "pixel_count": count,
            "percentage_of_valid": 100.0 * count / total if total else 0.0,
        }
    return result


def _read_raster(path: Path, grid: AnalysisGrid) -> np.ndarray:
    with rasterio.open(path) as dataset:
        validate_output_grid(dataset, grid, path)
        values = dataset.read(1).astype(np.float32, copy=False)
        if dataset.nodata is not None:
            values[values == dataset.nodata] = np.nan
        values[~np.isfinite(values)] = np.nan
        return values


def _read_mask(path: Path, grid: AnalysisGrid) -> np.ndarray:
    with rasterio.open(path) as dataset:
        validate_output_grid(dataset, grid, path)
        values = dataset.read(1, masked=False)
        return np.isfinite(values) & (values != dataset.nodata) & (values != 0)


def _difference(left: np.ndarray, right: np.ndarray, aoi: np.ndarray) -> dict[str, Any]:
    left_valid = np.isfinite(left) & aoi
    right_valid = np.isfinite(right) & aoi
    common = left_valid & right_valid
    gained = right_valid & ~left_valid
    lost = left_valid & ~right_valid
    difference = np.full(left.shape, np.nan, dtype=np.float32)
    difference[common] = right[common] - left[common]
    absolute = np.abs(difference[common]).astype(np.float64, copy=False)
    changed = common & (np.abs(difference) > 1e-6)
    return {
        "left_valid_pixels": int(np.count_nonzero(left_valid)),
        "right_valid_pixels": int(np.count_nonzero(right_valid)),
        "valid_mask_overlap_pixels": int(np.count_nonzero(common)),
        "valid_mask_overlap_percentage_of_left": (
            100.0 * np.count_nonzero(common) / np.count_nonzero(left_valid)
            if np.count_nonzero(left_valid)
            else 0.0
        ),
        "pixels_newly_gained_in_right": int(np.count_nonzero(gained)),
        "pixels_lost_in_right": int(np.count_nonzero(lost)),
        "pixels_whose_value_changes": int(np.count_nonzero(changed)),
        "mean_absolute_difference_common_valid": (
            float(np.mean(absolute)) if absolute.size else None
        ),
        "median_absolute_difference_common_valid": (
            float(np.median(absolute)) if absolute.size else None
        ),
        "p95_absolute_difference_common_valid": (
            float(np.percentile(absolute, 95)) if absolute.size else None
        ),
        "p99_absolute_difference_common_valid": (
            float(np.percentile(absolute, 99)) if absolute.size else None
        ),
        "maximum_absolute_difference_common_valid": float(np.max(absolute))
        if absolute.size
        else None,
        "difference_raster": difference,
    }


def _plot_index(
    path: Path, values: np.ndarray, grid: AnalysisGrid, title: str, label: str
) -> None:
    finite = _finite(values)
    low = max(-2.0, float(np.percentile(finite, 1)) if finite.size else -1.0)
    high = min(2.0, float(np.percentile(finite, 99)) if finite.size else 1.0)
    if not np.isfinite(low) or not np.isfinite(high) or low >= high:
        low, high = -1.0, 1.0
    masked = np.ma.masked_invalid(values)
    cmap = plt.get_cmap("RdYlGn").copy()
    cmap.set_bad("#d9d9d9")
    figure, axis = plt.subplots(figsize=(8, 5.5), constrained_layout=True)
    try:
        image = axis.imshow(
            masked,
            origin="upper",
            extent=grid.bounds,
            cmap=cmap,
            norm=Normalize(vmin=low, vmax=high, clip=True),
        )
        axis.set_title(
            f"{title} (display clipped to [{low:.2g}, {high:.2g}]; values unaltered)"
        )
        axis.set_xlabel("Easting (m), EPSG:32633")
        axis.set_ylabel("Northing (m), EPSG:32633")
        figure.colorbar(image, ax=axis, label=label, shrink=0.86)
        figure.savefig(path, dpi=120)
    finally:
        plt.close(figure)


def _plot_mask(path: Path, mask: np.ndarray, grid: AnalysisGrid, title: str) -> None:
    figure, axis = plt.subplots(figsize=(8, 5.5), constrained_layout=True)
    try:
        axis.imshow(
            np.ma.masked_where(~mask, mask),
            origin="upper",
            extent=grid.bounds,
            cmap="magma",
        )
        axis.set_title(title)
        axis.set_xlabel("Easting (m), EPSG:32633")
        axis.set_ylabel("Northing (m), EPSG:32633")
        figure.savefig(path, dpi=120)
    finally:
        plt.close(figure)


def _plot_difference(path: Path, difference: np.ndarray, grid: AnalysisGrid, title: str) -> None:
    finite = _finite(difference)
    limit = float(np.percentile(np.abs(finite), 99)) if finite.size else 1.0
    limit = max(0.05, min(2.0, limit))
    figure, axis = plt.subplots(figsize=(8, 5.5), constrained_layout=True)
    try:
        image = axis.imshow(
            np.ma.masked_invalid(difference),
            origin="upper",
            extent=grid.bounds,
            cmap="RdBu_r",
            norm=TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit),
        )
        axis.set_title(f"{title} (display clipped to ±{limit:.2g}; values unaltered)")
        axis.set_xlabel("Easting (m), EPSG:32633")
        axis.set_ylabel("Northing (m), EPSG:32633")
        figure.colorbar(image, ax=axis, label="difference", shrink=0.86)
        figure.savefig(path, dpi=120)
    finally:
        plt.close(figure)


def _qa_images(
    year: int,
    root: Path,
    grid: AnalysisGrid,
    values: dict[str, dict[str, np.ndarray]],
) -> dict[str, str]:
    qa_dir = root / str(year) / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for index in ("nbr", "ndvi"):
        for mode in (ReflectanceTreatment.PRESERVE, ReflectanceTreatment.CLAMP_ZERO):
            path = qa_dir / f"{index}-{mode.value}.png"
            _plot_index(
                path,
                values[mode.value][index],
                grid,
                f"{year} {index.upper()} {mode.value}",
                index.upper(),
            )
            paths[f"{index}_{mode.value}"] = str(path)
        extreme_path = qa_dir / f"{index}-preserve-abs-greater-than-1.png"
        _plot_mask(
            extreme_path,
            np.isfinite(values["preserve"][index]) & (np.abs(values["preserve"][index]) > 1),
            grid,
            f"{year} {index.upper()} PRESERVE: abs(index) > 1",
        )
        paths[f"{index}_preserve_abs_greater_than_1"] = str(extreme_path)
        diff = values["preserve"][index] - values["clamp-zero"][index]
        diff_path = qa_dir / f"{index}-preserve-minus-clamp-zero.png"
        _plot_difference(
            diff_path, diff, grid, f"{year} PRESERVE − CLAMP_ZERO {index.upper()}"
        )
        paths[f"{index}_preserve_minus_clamp_zero"] = str(diff_path)
    return paths


def _empty_band_stats() -> dict[str, Any]:
    return {"count": 0, "min": None, "median": None, "max": None, "_samples": []}


def _band_stats(values: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    selected = _finite(values[mask])
    if not selected.size:
        return _empty_band_stats()
    return {
        "count": int(selected.size),
        "min": float(np.min(selected)),
        "median": float(np.median(selected)),
        "max": float(np.max(selected)),
    }


def _source_handling_diagnostics(
    items: Sequence[dict[str, Any]], grid: AnalysisGrid
) -> dict[str, Any]:
    """Scan source observations once for negative-band and denominator evidence."""
    aggregate: dict[str, Any] = {}
    for index, (first_name, second_name) in INDEX_PAIRS.items():
        aggregate[index] = {
            "observation_source_valid_count": 0,
            "observation_valid_count_by_mode": {mode.value: 0 for mode in ReflectanceTreatment},
            "newly_admitted_by_mode": {
                mode.value: {
                    "pixel_count": 0,
                    "negative_combinations": {
                        "first_negative_only": 0,
                        "second_negative_only": 0,
                        "multiple_required_bands_negative": 0,
                    },
                    "band_statistics": {
                        first_name: _empty_band_stats(),
                        second_name: _empty_band_stats(),
                    },
                }
                for mode in (ReflectanceTreatment.PRESERVE, ReflectanceTreatment.CLAMP_ZERO)
            },
            "preserve_denominator": {
                "finite_nonzero_count": 0,
                "zero_count": 0,
                "near_zero": {str(threshold): 0 for threshold in NEAR_ZERO_THRESHOLDS},
                "near_zero_percentage_of_preserve_valid": {
                    str(threshold): 0.0 for threshold in NEAR_ZERO_THRESHOLDS
                },
            },
        }
    processable_items = [item for item in items if _processable(item)]
    for item in processable_items:
        result = read_item_indices(
            item,
            grid,
            _asset,
            treatment=ReflectanceTreatment.PRESERVE,
            return_reflectance=True,
        )
        reflectance = result["reflectance"]
        scl_valid = result["scl_valid"]
        for index, (first_name, second_name) in INDEX_PAIRS.items():
            first = reflectance[first_name]
            second = reflectance[second_name]
            required = scl_valid & np.isfinite(first) & np.isfinite(second)
            stages = {
                mode: index_validity_stages(first, second, scl_valid, treatment=mode)
                for mode in ReflectanceTreatment
            }
            record = aggregate[index]
            record["observation_source_valid_count"] += int(np.count_nonzero(required))
            for mode in ReflectanceTreatment:
                record["observation_valid_count_by_mode"][mode.value] += int(
                    np.count_nonzero(stages[mode]["final_valid"])
                )
            preserve_valid = stages[ReflectanceTreatment.PRESERVE]["final_valid"]
            denominator = stages[ReflectanceTreatment.PRESERVE]["denominator"]
            finite_nonzero = preserve_valid & np.isfinite(denominator) & (denominator != 0)
            near = record["preserve_denominator"]
            near["finite_nonzero_count"] += int(np.count_nonzero(finite_nonzero))
            near["zero_count"] += int(np.count_nonzero(required & (denominator == 0)))
            for threshold in NEAR_ZERO_THRESHOLDS:
                near["near_zero"][str(threshold)] += int(
                    np.count_nonzero(finite_nonzero & (np.abs(denominator) < threshold))
                )
            for mode in (ReflectanceTreatment.PRESERVE, ReflectanceTreatment.CLAMP_ZERO):
                newly = stages[mode]["final_valid"] & ~stages[
                    ReflectanceTreatment.REJECT
                ]["final_valid"]
                new_record = record["newly_admitted_by_mode"][mode.value]
                count = int(np.count_nonzero(newly))
                new_record["pixel_count"] += count
                first_negative = first < 0
                second_negative = second < 0
                new_record["negative_combinations"]["first_negative_only"] += int(
                    np.count_nonzero(newly & first_negative & ~second_negative)
                )
                new_record["negative_combinations"]["second_negative_only"] += int(
                    np.count_nonzero(newly & ~first_negative & second_negative)
                )
                new_record["negative_combinations"]["multiple_required_bands_negative"] += int(
                    np.count_nonzero(newly & first_negative & second_negative)
                )
                for band_name, band_values in ((first_name, first), (second_name, second)):
                    stats = new_record["band_statistics"][band_name]
                    selected = _finite(band_values[newly])
                    if selected.size:
                        previous_count = stats["count"]
                        previous_min = stats["min"]
                        previous_max = stats["max"]
                        stats["count"] += int(selected.size)
                        stats["min"] = float(np.min(selected)) if previous_count == 0 else min(
                            previous_min, float(np.min(selected))
                        )
                        stats["max"] = float(np.max(selected)) if previous_count == 0 else max(
                            previous_max, float(np.max(selected))
                        )
                        # Keep a bounded deterministic sample so the final
                        # report can include a useful aggregate median without
                        # retaining all newly admitted source pixels.
                        step = max(1, selected.size // 20_000)
                        stats["_samples"].append(
                            selected[::step][:20_000].astype(np.float32, copy=True)
                        )
    for record in aggregate.values():
        preserve_count = record["preserve_denominator"]["finite_nonzero_count"]
        for threshold in NEAR_ZERO_THRESHOLDS:
            count = record["preserve_denominator"]["near_zero"][str(threshold)]
            record["preserve_denominator"]["near_zero_percentage_of_preserve_valid"][
                str(threshold)
            ] = 100.0 * count / preserve_count if preserve_count else 0.0
        for new_record in record["newly_admitted_by_mode"].values():
            for stats in new_record["band_statistics"].values():
                if stats["count"]:
                    sampled = np.concatenate(stats["_samples"])
                    stats["median"] = float(np.median(sampled))
                stats.pop("_samples", None)
    return aggregate


def _footprint_stats(values: np.ndarray, footprint: np.ndarray) -> dict[str, Any]:
    selected = _finite(values[footprint])
    footprint_count = int(np.count_nonzero(footprint))
    valid = int(selected.size)
    result: dict[str, Any] = {
        "footprint_pixel_count": footprint_count,
        "valid_pixel_count": valid,
        "valid_percentage": 100.0 * valid / footprint_count if footprint_count else 0.0,
        "median": float(np.median(selected)) if valid else None,
        "p10": float(np.percentile(selected, 10)) if valid else None,
        "p90": float(np.percentile(selected, 90)) if valid else None,
    }
    for name, threshold in (
        ("outside_minus_1_to_1", 1),
        ("abs_greater_than_2", 2),
        ("abs_greater_than_5", 5),
    ):
        count = int(np.count_nonzero(np.abs(selected) > threshold)) if valid else 0
        if name == "outside_minus_1_to_1":
            count = int(np.count_nonzero((selected < -1) | (selected > 1))) if valid else 0
        result[name] = {"pixel_count": count, "fraction_of_valid": count / valid if valid else 0.0}
    return result


def _disturbance_stats(
    year: int,
    mode_values: dict[str, dict[str, np.ndarray]],
    grid: AnalysisGrid,
) -> dict[str, Any]:
    mask_path = Path("data/derived/disturbance/disturbance_mask.tif")
    labels_path = Path("data/derived/disturbance/disturbance_labels.tif")
    footprint = _read_mask(mask_path, grid) & grid.aoi_mask
    with rasterio.open(labels_path) as dataset:
        validate_output_grid(dataset, grid, labels_path)
        labels = dataset.read(1)
        if dataset.nodata is not None:
            labels[labels == dataset.nodata] = 0
    objects = json.loads(
        Path("data/derived/disturbance/disturbance-summary.json").read_text()
    )["objects"]
    largest = sorted(
        objects, key=lambda obj: (-float(obj["area_ha"]), obj["disturbance_id"])
    )[:5]
    result: dict[str, Any] = {
        "footprint_pixel_count": int(np.count_nonzero(footprint)),
        "modes": {},
    }
    for mode, values in mode_values.items():
        result["modes"][mode] = {
            index: _footprint_stats(values[index], footprint) for index in ("nbr", "ndvi")
        }
        result["modes"][mode]["largest_objects"] = {}
        for obj in largest:
            object_mask = footprint & (labels == int(obj["component_label"]))
            result["modes"][mode]["largest_objects"][obj["disturbance_id"]] = {
                "area_ha": obj["area_ha"],
                "component_label": obj["component_label"],
                "nbr": _footprint_stats(values["nbr"], object_mask),
                "ndvi": _footprint_stats(values["ndvi"], object_mask),
            }
    return result


def _coarse_temporal_check(
    mode_values: dict[str, dict[str, np.ndarray]], grid: AnalysisGrid
) -> dict[str, Any]:
    historical: dict[str, Any] = {}
    for year in (2019, 2020, 2021):
        summary_path = Path(f"data/derived/annual/{year}/annual-summary.json")
        summary = json.loads(summary_path.read_text())
        historical[str(year)] = {
            "nbr": summary.get("nbr_distribution"),
            "ndvi": summary.get("ndvi_distribution"),
        }
    return {
        "historical_canonical_reject_distributions": historical,
        "candidate_distributions": {
            mode: {index: _index_distribution(values[index]) for index in ("nbr", "ndvi")}
            for mode, values in mode_values.items()
        },
        "interpretation": (
            "Coarse distribution comparison only; it does not establish biological continuity "
            "or a recovery trend."
        ),
    }


def _variant_values(year: int, root: Path, grid: AnalysisGrid) -> dict[str, dict[str, np.ndarray]]:
    values: dict[str, dict[str, np.ndarray]] = {}
    canonical = {
        "nbr": _read_raster(Path(f"data/derived/annual/{year}/nbr.tif"), grid),
        "ndvi": _read_raster(Path(f"data/derived/annual/{year}/ndvi.tif"), grid),
    }
    values[ReflectanceTreatment.REJECT.value] = canonical
    for mode in (ReflectanceTreatment.PRESERVE, ReflectanceTreatment.CLAMP_ZERO):
        values[mode.value] = {
            index: _read_raster(root / str(year) / mode.value / f"{index}.tif", grid)
            for index in ("nbr", "ndvi")
        }
    return values


def _year_report(
    config_path: Path,
    inventory_path: Path,
    root: Path,
    year: int,
) -> dict[str, Any]:
    config = load_config(config_path)
    grid = _approved_grid(config)
    inventory = load_inventory(inventory_path)
    items = sorted(
        [item for item in inventory if item.get("year") == year and _processable(item)],
        key=lambda item: (str(item.get("datetime") or ""), str(item["id"])),
    )
    mode_values = _variant_values(year, root, grid)
    aoi = grid.aoi_mask
    variants: dict[str, Any] = {}
    comparisons: dict[str, Any] = {}
    for mode in ReflectanceTreatment:
        variants[mode.value] = {
            "coverage": {
                index: _coverage(mode_values[mode.value][index], aoi)
                for index in ("nbr", "ndvi")
            },
            "index_distributions": {
                index: _index_distribution(mode_values[mode.value][index])
                for index in ("nbr", "ndvi")
            },
            "extreme_values": {
                index: _extremes(mode_values[mode.value][index]) for index in ("nbr", "ndvi")
            },
        }
    for left, right in (
        (ReflectanceTreatment.REJECT.value, ReflectanceTreatment.PRESERVE.value),
        (ReflectanceTreatment.REJECT.value, ReflectanceTreatment.CLAMP_ZERO.value),
        (ReflectanceTreatment.PRESERVE.value, ReflectanceTreatment.CLAMP_ZERO.value),
    ):
        comparisons[f"{left}_vs_{right}"] = {
            index: _difference(mode_values[left][index], mode_values[right][index], aoi)
            for index in ("nbr", "ndvi")
        }
        for index in ("nbr", "ndvi"):
            comparisons[f"{left}_vs_{right}"][index].pop("difference_raster")
    qa = _qa_images(year, root, grid, mode_values)
    return {
        "year": year,
        "processable_item_count": len(items),
        "variant_paths": {
            "reject": str(PRODUCTION_ROOT / str(year)),
            "preserve": str(root / str(year) / ReflectanceTreatment.PRESERVE.value),
            "clamp-zero": str(root / str(year) / ReflectanceTreatment.CLAMP_ZERO.value),
        },
        "variants": variants,
        "composite_comparisons": comparisons,
        "disturbance_footprint": _disturbance_stats(year, mode_values, grid),
        "negative_band_combinations": _source_handling_diagnostics(items, grid),
        "qa_references": qa,
        "coarse_temporal_consistency": _coarse_temporal_check(mode_values, grid),
    }


def evaluate_year(
    config_path: Path,
    inventory_path: Path,
    output_root: Path,
    temp_root: Path,
    year: int,
) -> dict[str, Any]:
    """Build preserve/clamp variants sequentially, then analyze all modes."""
    _assert_diagnostic_path(output_root, output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    build_records: dict[str, Any] = {}
    for mode in (ReflectanceTreatment.PRESERVE, ReflectanceTreatment.CLAMP_ZERO):
        variant_dir = output_root / str(year) / mode.value
        _assert_diagnostic_path(variant_dir, output_root)
        start = time.monotonic()
        summary = build(
            config_path,
            inventory_path,
            output_root,
            temp_root,
            year,
            treatment=mode,
            output_dir=variant_dir,
        )
        build_records[mode.value] = {
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "summary": summary,
            "temporary_workspace_cleaned": not any(temp_root.rglob(f"{year}-*"))
            if temp_root.exists()
            else True,
        }
    report = _year_report(config_path, inventory_path, output_root, year)
    report["build_records"] = build_records
    return report


def _existing_year_reports(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Read both the current report shape and the pre-fix nested merge shape."""
    candidate = payload.get("year_reports", {})
    direct = {
        key: value
        for key, value in candidate.items()
        if str(key).isdigit() and isinstance(value, dict) and "year" in value
    }
    if direct:
        reports = direct
    else:
        nested = candidate.get("year_reports", {})
        reports = {
            key: value
            for key, value in nested.items()
            if str(key).isdigit() and isinstance(value, dict) and "year" in value
        }
    for key, report in reports.items():
        year = int(key)
        report["variant_paths"] = {
            "reject": str(PRODUCTION_ROOT / str(year)),
            "preserve": str(DEFAULT_ROOT / str(year) / ReflectanceTreatment.PRESERVE.value),
            "clamp-zero": str(DEFAULT_ROOT / str(year) / ReflectanceTreatment.CLAMP_ZERO.value),
        }
    return reports


def _report_payload(
    args: argparse.Namespace, reports: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    return {
        "methodology": {
            "purpose": (
                "Controlled diagnostic evaluation; production methodology and canonical "
                "annual outputs unchanged."
            ),
            "negative_reflectance_context": (
                "Sentinel-2 L2A radiometric offsets can encode valid negative surface "
                "reflectance."
            ),
            "source_nodata": (
                "Source DN nodata is masked before scale/offset conversion and remains "
                "invalid in every mode."
            ),
            "scl_validity": (
                "Existing SCL invalid classes and nearest-neighbour mask are unchanged."
            ),
            "index_formulas": {
                "nbr": "(NIR - SWIR2) / (NIR + SWIR2)",
                "ndvi": "(NIR - RED) / (NIR + RED)",
            },
            "denominator_rule": (
                "Finite and nonzero; no epsilon threshold and no analytical clipping."
            ),
            "production_behavior": (
                "REJECT remains the default and canonical annual outputs were not rebuilt."
            ),
        },
        "years": [int(year) for year in sorted(reports)],
        "modes": [mode.value for mode in ReflectanceTreatment],
        "provenance": {
            "config": str(args.config),
            "inventory": str(args.inventory),
            "canonical_root": str(PRODUCTION_ROOT),
            "diagnostic_root": str(args.output_root),
            "disturbance_mask": "data/derived/disturbance/disturbance_mask.tif",
            "disturbance_labels": "data/derived/disturbance/disturbance_labels.tif",
        },
        "year_reports": {key: reports[key] for key in sorted(reports)},
        "recommendation": {
            "mode": "REJECT",
            "status": "diagnostic recommendation only; not adopted",
            "reason": (
                "PRESERVE restores coverage but produces widespread unstable/extreme ratios; "
                "CLAMP_ZERO is bounded but saturates dark pixels, especially NDVI, to values "
                "that are not analytically credible. Neither alternative passes the stated "
                "criteria better than retaining holes."
            ),
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, choices=YEARS, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--inventory", type=Path, default=Path("data/inventory/stac-items.json"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--temp-root", type=Path, default=Path("data/.tmp/reflectance"))
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="repair/rewrite the generated report from existing diagnostic outputs",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report_path = args.output_root / "reflectance-handling-evaluation.json"
    previous = json.loads(report_path.read_text()) if report_path.exists() else {}
    reports = _existing_year_reports(previous)
    year_report: dict[str, Any] = {}
    if not args.report_only:
        year_report = evaluate_year(
            args.config, args.inventory, args.output_root, args.temp_root, args.year
        )
        reports[str(args.year)] = year_report
    payload = _report_payload(args, reports)
    _write_json(report_path, payload)
    if year_report:
        print(json.dumps(year_report, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
