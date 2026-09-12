"""Build local NBR spectral-recovery analysis from canonical annual rasters.

This command intentionally performs no STAC access and never rebuilds annual
composites.  It reads the fixed disturbance labels and one annual pair at a
time, producing analytical GeoTIFFs, deterministic JSON, and restrained QA
figures beneath ``data/derived/recovery``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from matplotlib import pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap

from .build_annual_batch import classify_annual_output
from .build_annual_series import _approved_grid, validate_output_grid
from .config import ProjectConfig, load_config
from .recovery import (
    GOOD_MIN,
    PIXEL_AREA_HECTARES,
    RECOVERY_NODATA,
    USABLE_MIN,
    calculate_recovery,
    ensure_json_safe,
    landscape_statistics,
    object_statistics,
    validate_denominators,
)

ANNUAL_ROOT = Path("data/derived/annual")
DISTURBANCE_ROOT = Path("data/derived/disturbance")
OUTPUT_ROOT = Path("data/derived/recovery")
YEARS = tuple(range(2017, 2027))
ANNUAL_FILES = ("nbr.tif", "ndvi.tif", "valid_count.tif")
DISTURBANCE_FILES = ("disturbance_mask.tif", "disturbance_labels.tif")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_paths(
    annual_root: Path, disturbance_root: Path, years: tuple[int, ...]
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for year in years:
        for filename in (*ANNUAL_FILES, "annual-summary.json"):
            paths[f"annual/{year}/{filename}"] = annual_root / str(year) / filename
    for filename in DISTURBANCE_FILES:
        paths[f"disturbance/{filename}"] = disturbance_root / filename
    paths["disturbance/disturbances.geojson"] = disturbance_root / "disturbances.geojson"
    paths["disturbance/disturbance-summary.json"] = disturbance_root / "disturbance-summary.json"
    return paths


def _validate_raster(path: Path, grid: Any) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required canonical raster is missing: {path}")
    with rasterio.open(path) as dataset:
        if dataset.count != 1:
            raise ValueError(f"{path} has {dataset.count} bands; expected one")
        validate_output_grid(dataset, grid, path)
        if not np.allclose(dataset.res, (20.0, 20.0), atol=1e-9):
            raise ValueError(f"{path} has resolution {dataset.res}; expected (20.0, 20.0)")
        return {
            "dtype": dataset.dtypes[0],
            "nodata": dataset.nodata,
            "crs": str(dataset.crs),
            "width": dataset.width,
            "height": dataset.height,
            "transform": list(dataset.transform),
            "bounds": list(dataset.bounds),
        }


def _read_values(path: Path, grid: Any) -> np.ndarray:
    _validate_raster(path, grid)
    with rasterio.open(path) as dataset:
        values = dataset.read(1, masked=False).astype(np.float32)
        if dataset.nodata is not None:
            values[values == dataset.nodata] = np.nan
    values[~np.isfinite(values)] = np.nan
    return values


def validate_inputs(
    config: ProjectConfig,
    annual_root: Path = ANNUAL_ROOT,
    disturbance_root: Path = DISTURBANCE_ROOT,
) -> tuple[Any, dict[str, np.ndarray], dict[int, dict[str, Any]], dict[str, Path]]:
    """Validate all canonical inputs and load only fixed baseline/label arrays."""
    if tuple(config.analysis_years) != YEARS:
        raise ValueError(f"recovery requires configured analysis years {list(YEARS)}")
    grid = _approved_grid(config)
    paths = _canonical_paths(annual_root, disturbance_root, YEARS)
    for year in YEARS:
        result = classify_annual_output(annual_root / str(year), year, config)
        if result.state != "COMPLETE":
            raise ValueError(f"annual {year} is not COMPLETE: {'; '.join(result.reasons)}")
        for filename in ANNUAL_FILES:
            _validate_raster(paths[f"annual/{year}/{filename}"], grid)
    for filename in DISTURBANCE_FILES:
        _validate_raster(paths[f"disturbance/{filename}"], grid)
    for path in (
        paths["disturbance/disturbances.geojson"],
        paths["disturbance/disturbance-summary.json"],
    ):
        if not path.is_file():
            raise FileNotFoundError(f"Required disturbance input is missing: {path}")

    baseline = {
        "nbr_2017": _read_values(paths["annual/2017/nbr.tif"], grid),
        "nbr_2018": _read_values(paths["annual/2018/nbr.tif"], grid),
    }
    labels = _read_values(paths["disturbance/disturbance_labels.tif"], grid)
    labels = np.where(np.isfinite(labels), labels, 0).astype(np.int32)
    mask = _read_values(paths["disturbance/disturbance_mask.tif"], grid)
    retained = labels > 0
    if not np.array_equal(retained, mask == 1):
        raise ValueError("disturbance mask and positive disturbance labels do not match")
    labels_present = sorted(int(value) for value in np.unique(labels) if value > 0)
    if labels_present != list(range(1, 81)):
        raise ValueError(
            f"expected disturbance labels 1..80, found {labels_present[:5]}..{labels_present[-5:]}"
        )

    geojson = json.loads(paths["disturbance/disturbances.geojson"].read_text(encoding="utf-8"))
    features = geojson.get("features")
    if not isinstance(features, list) or len(features) != 80:
        raise ValueError("disturbance GeoJSON must contain exactly 80 features")
    geo_ids = [feature.get("properties", {}).get("disturbance_id") for feature in features]
    expected_ids = [f"disturbance-{label:03d}" for label in range(1, 81)]
    if sorted(geo_ids) != expected_ids:
        raise ValueError("disturbance GeoJSON IDs do not match fixed labels 1..80")
    summary = json.loads(paths["disturbance/disturbance-summary.json"].read_text(encoding="utf-8"))
    objects = summary.get("objects")
    if not isinstance(objects, list) or len(objects) != 80:
        raise ValueError("disturbance summary must contain exactly 80 objects")
    metadata: dict[int, dict[str, Any]] = {}
    for item in objects:
        label = int(item["component_label"])
        if label in metadata or item["disturbance_id"] != f"disturbance-{label:03d}":
            raise ValueError("disturbance summary has non-deterministic or duplicate labels")
        actual_count = int(np.count_nonzero(labels == label))
        if actual_count != int(item["pixel_count"]):
            raise ValueError(f"disturbance label {label} pixel count disagrees with summary")
        metadata[label] = item
    if sorted(metadata) != list(range(1, 81)):
        raise ValueError("disturbance summary labels do not cover 1..80")
    baseline["labels"] = labels
    return grid, baseline, metadata, paths


def _write_recovery_raster(path: Path, values: np.ndarray, grid: Any) -> None:
    profile = {
        "driver": "GTiff",
        "height": grid.height,
        "width": grid.width,
        "count": 1,
        "dtype": "float32",
        "crs": grid.crs,
        "transform": grid.transform,
        "nodata": RECOVERY_NODATA,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "compress": "deflate",
        "zlevel": 6,
        "BIGTIFF": "IF_SAFER",
    }
    output = np.full(values.shape, RECOVERY_NODATA, dtype=np.float32)
    valid = np.isfinite(values)
    output[valid] = values[valid].astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(output, 1)


def _load_completeness_reference(path: Path) -> dict[int, dict[str, Any]] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    landscape = data.get("landscape")
    disturbances = data.get("disturbances")
    if not isinstance(landscape, list) or not isinstance(disturbances, list):
        raise ValueError(f"invalid annual completeness diagnostic: {path}")
    result: dict[int, dict[str, Any]] = {
        int(item["year"]): item for item in landscape if isinstance(item, dict) and "year" in item
    }
    if set(result) != set(YEARS):
        raise ValueError("annual completeness diagnostic does not cover 2017..2026")
    return result


def _reconcile_completeness(
    year: int,
    landscape: dict[str, Any],
    objects: list[dict[str, Any]],
    reference: dict[int, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if reference is None:
        return None
    expected = reference[year]
    expected_fraction = float(expected["retained_disturbance_nbr_valid_fraction"])
    actual_fraction = float(landscape["valid_nbr_fraction"])
    counts: dict[str, int] = {status: 0 for status in ("GOOD", "USABLE_WITH_COVERAGE_FLAG", "POOR")}
    for record in objects:
        counts[record["nbr_coverage_status"]] += 1
    expected_counts = expected["readiness_counts"]
    if not np.isclose(actual_fraction, expected_fraction, rtol=0, atol=1e-12):
        raise ValueError(f"annual completeness mismatch for {year}: valid fraction differs")
    if counts != {key: int(expected_counts[key]) for key in counts}:
        raise ValueError(f"annual completeness mismatch for {year}: object status counts differ")
    return {"reference_valid_fraction": expected_fraction, "reference_status_counts": counts}


def _plot_landscape(
    years: list[int], values: list[float | None], ylabel: str, title: str, path: Path
) -> None:
    fig, axis = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    axis.plot(years, values, marker="o", color="#225ea8")
    axis.set_xlabel("Annual August composite year")
    axis.set_ylabel(ylabel)
    axis.set_xticks(years)
    axis.grid(True, alpha=0.3)
    axis.set_title(title)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_trajectories(series_by_id: dict[str, list[dict[str, Any]]], path: Path) -> None:
    fig, axis = plt.subplots(figsize=(9, 5.5), constrained_layout=True)
    colors = plt.get_cmap("tab10").colors
    for index, disturbance_id in enumerate(sorted(series_by_id)):
        series = series_by_id[disturbance_id]
        years = np.array([item["year"] for item in series])
        values = np.array(
            [
                item["recovery_median"] if item["coverage_status"] != "POOR" else np.nan
                for item in series
            ],
            dtype=float,
        )
        color = colors[index % len(colors)]
        axis.plot(years, values, marker="o", label=disturbance_id, color=color)
        poor = np.array([item["coverage_status"] == "POOR" for item in series])
        poor_values = np.array([item["recovery_median"] for item in series], dtype=float)
        axis.scatter(years[poor], poor_values[poor], marker="x", color=color, alpha=0.8)
        usable = np.array(
            [item["coverage_status"] == "USABLE_WITH_COVERAGE_FLAG" for item in series]
        )
        axis.scatter(years[usable], values[usable], marker="^", facecolors="none", edgecolors=color)
    axis.axvline(2017, color="black", linestyle="--", linewidth=0.8)
    axis.axvline(2018, color="black", linestyle=":", linewidth=0.9)
    axis.text(
        2017, 1.02, "2017 baseline", transform=axis.get_xaxis_transform(), ha="center", fontsize=8
    )
    axis.text(
        2018, 0.96, "2018 benchmark", transform=axis.get_xaxis_transform(), ha="center", fontsize=8
    )
    axis.set_xlabel("Annual August composite year")
    axis.set_ylabel("Median NBR recovery fraction")
    axis.set_xticks(list(YEARS))
    axis.grid(True, alpha=0.3)
    axis.legend(ncol=2, fontsize=8)
    axis.set_title("Fixed disturbance-object spectral recovery (medians)")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_map(values: np.ndarray, labels: np.ndarray, grid: Any, path: Path) -> None:
    display = np.where(labels > 0, values, np.nan)
    fig, axis = plt.subplots(figsize=(8, 6), constrained_layout=True)
    image = axis.imshow(display, cmap="RdYlGn", vmin=-0.25, vmax=1.25, extent=grid.bounds)
    fig.colorbar(image, ax=axis, label="NBR recovery fraction")
    axis.set_xlabel("Easting (m)")
    axis.set_ylabel("Northing (m)")
    axis.set_title("2026 NBR recovery fraction inside fixed disturbance footprint")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_heatmap(statuses: list[list[str]], path: Path) -> None:
    codes = {"POOR": 0, "USABLE_WITH_COVERAGE_FLAG": 1, "GOOD": 2}
    values = np.array([[codes[status] for status in row] for row in statuses])
    fig, axis = plt.subplots(figsize=(8, 10), constrained_layout=True)
    cmap = ListedColormap(["#d73027", "#fee08b", "#1a9850"])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], cmap.N)
    image = axis.imshow(values, cmap=cmap, norm=norm, aspect="auto")
    axis.set_xticks(range(len(YEARS)), [str(year) for year in YEARS], rotation=45, ha="right")
    axis.set_yticks(range(80), [f"disturbance-{i:03d}" for i in range(1, 81)], fontsize=6)
    axis.set_xlabel("Year")
    axis.set_title("NBR coverage status by fixed disturbance object")
    colorbar = fig.colorbar(image, ax=axis, ticks=[0, 1, 2], shrink=0.7)
    colorbar.ax.set_yticklabels(["POOR", "USABLE_WITH_COVERAGE_FLAG", "GOOD"])
    fig.savefig(path, dpi=150)
    plt.close(fig)


def build(
    config_path: Path = Path("config/project.toml"),
    annual_root: Path = ANNUAL_ROOT,
    disturbance_root: Path = DISTURBANCE_ROOT,
    output_root: Path = OUTPUT_ROOT,
    completeness_path: Path = Path(
        "data/derived/diagnostics/annual-completeness/annual-nbr-completeness.json"
    ),
) -> dict[str, Any]:
    """Run the complete local recovery analysis and write all outputs."""
    config = load_config(config_path)
    paths = _canonical_paths(annual_root, disturbance_root, YEARS)
    before_hashes = {name: _sha256(path) for name, path in paths.items()}
    grid, baseline, metadata, paths = validate_inputs(config, annual_root, disturbance_root)
    labels = baseline["labels"]
    denominator = validate_denominators(
        baseline["nbr_2017"],
        baseline["nbr_2018"],
        labels,
        baseline_nbr_min=config.baseline_nbr_min,
        dnbr_min=config.dnbr_min,
    )
    reference = _load_completeness_reference(completeness_path)
    output_root.mkdir(parents=True, exist_ok=True)
    rasters_dir = output_root / "rasters"
    qa_dir = output_root / "qa"
    rasters_dir.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)
    records_by_label: dict[int, list[dict[str, Any]]] = {label: [] for label in range(1, 81)}
    landscape_series: list[dict[str, Any]] = []
    reconciliation: dict[str, Any] = {}
    for year in YEARS:
        nbr = _read_values(paths[f"annual/{year}/nbr.tif"], grid)
        ndvi = _read_values(paths[f"annual/{year}/ndvi.tif"], grid)
        recovery = calculate_recovery(baseline["nbr_2017"], baseline["nbr_2018"], nbr, labels)
        raster_path = rasters_dir / f"recovery_{year}.tif"
        _write_recovery_raster(raster_path, recovery, grid)
        objects = object_statistics(labels, nbr, recovery, ndvi, pixel_area_ha=PIXEL_AREA_HECTARES)
        for record in objects:
            record["year"] = year
            records_by_label[int(record["component_label"])].append(record)
        landscape = landscape_statistics(
            labels, nbr, recovery, ndvi, pixel_area_ha=PIXEL_AREA_HECTARES
        )
        landscape["year"] = year
        landscape["recovery_threshold_denominator"] = "valid recovery pixels only"
        landscape_series.append(landscape)
        reconciliation[str(year)] = _reconcile_completeness(year, landscape, objects, reference)
        del nbr, ndvi, recovery, objects

    disturbances: list[dict[str, Any]] = []
    for label in range(1, 81):
        series = records_by_label[label]
        disturbances.append(
            {
                "disturbance_id": f"disturbance-{label:03d}",
                "component_label": label,
                "area_ha": float(np.count_nonzero(labels == label) * PIXEL_AREA_HECTARES),
                "series": series,
            }
        )
    all_records = [record for series in records_by_label.values() for record in series]
    status_counts = {
        status: sum(record["nbr_coverage_status"] == status for record in all_records)
        for status in ("GOOD", "USABLE_WITH_COVERAGE_FLAG", "POOR")
    }
    zero_valid = sum(record["recovery_valid_pixel_count"] == 0 for record in all_records)
    status_by_year: list[dict[str, Any]] = []
    for year, landscape in zip(YEARS, landscape_series):
        records = [record for record in all_records if record["year"] == year]
        fractions = np.array([record["nbr_valid_fraction"] for record in records], dtype=float)
        status_by_year.append(
            {
                "year": year,
                "GOOD": sum(record["nbr_coverage_status"] == "GOOD" for record in records),
                "USABLE_WITH_COVERAGE_FLAG": sum(
                    record["nbr_coverage_status"] == "USABLE_WITH_COVERAGE_FLAG"
                    for record in records
                ),
                "POOR": sum(record["nbr_coverage_status"] == "POOR" for record in records),
                "median_object_coverage": float(np.median(fractions)),
                "minimum_object_coverage": float(np.min(fractions)),
                "zero_valid_object_count": sum(
                    record["recovery_valid_pixel_count"] == 0 for record in records
                ),
            }
        )

    input_hashes = dict(before_hashes)
    timeseries = {
        "years": list(YEARS),
        "coverage_thresholds": {"good_min": GOOD_MIN, "usable_min": USABLE_MIN},
        "disturbances": disturbances,
    }
    timeseries_path = output_root / "disturbance-timeseries.json"
    timeseries_path.write_text(
        json.dumps(ensure_json_safe(timeseries), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    largest_five = {
        disturbance["disturbance_id"]: [
            {
                "year": item["year"],
                "nbr_valid_fraction": item["nbr_valid_fraction"],
                "nbr_median": item["nbr_median"],
                "recovery_median": item["recovery_median"],
                "recovery_p10": item["recovery_p10"],
                "recovery_p90": item["recovery_p90"],
                "coverage_status": item["nbr_coverage_status"],
            }
            for item in disturbance["series"]
        ]
        for disturbance in disturbances[:5]
    }
    _plot_landscape(
        list(YEARS),
        [item["nbr_median"] for item in landscape_series],
        "NBR median",
        "Landscape-wide median NBR inside fixed disturbance footprint",
        qa_dir / "landscape_nbr_median_by_year.png",
    )
    _plot_landscape(
        list(YEARS),
        [item["recovery_median"] for item in landscape_series],
        "NBR recovery fraction",
        "Landscape-wide median NBR recovery fraction",
        qa_dir / "landscape_recovery_median_by_year.png",
    )
    _plot_trajectories(
        {key: largest_five[key] for key in sorted(largest_five)},
        qa_dir / "disturbances_001_005_recovery_trajectories.png",
    )
    recovery_2026 = _read_values(rasters_dir / "recovery_2026.tif", grid)
    _plot_map(recovery_2026, labels, grid, qa_dir / "recovery_2026_map.png")
    statuses = [
        [record["nbr_coverage_status"] for record in records_by_label[label]]
        for label in range(1, 81)
    ]
    _plot_heatmap(statuses, qa_dir / "coverage_status_heatmap.png")
    del recovery_2026

    after_hashes = {name: _sha256(path) for name, path in paths.items()}
    unchanged = before_hashes == after_hashes
    if not unchanged:
        changed = [name for name in before_hashes if before_hashes[name] != after_hashes[name]]
        raise RuntimeError(f"canonical inputs changed during recovery build: {changed}")
    summary = {
        "methodology": {
            "version": "nbr-recovery-v1",
            "indicator": "NBR primary; NDVI contextual only",
            "formula": "(NBR_y - NBR_2018) / (NBR_2017 - NBR_2018)",
            "annual_composite": "August annual canonical outputs",
            "pixel_first_aggregation": True,
            "clamping": "none",
            "recovery_threshold_denominator": "valid recovery pixels only",
        },
        "inputs": {
            "config": str(config_path),
            "canonical_paths": {key: str(path) for key, path in paths.items()},
        },
        "canonical_input_sha256": input_hashes,
        "canonical_input_sha256_before": before_hashes,
        "canonical_input_sha256_after": after_hashes,
        "canonical_inputs_unchanged": unchanged,
        "analysis_grid": {
            "crs": grid.crs,
            "resolution_m": grid.resolution,
            "bounds": list(grid.bounds),
            "width": grid.width,
            "height": grid.height,
            "pixel_area_hectares": PIXEL_AREA_HECTARES,
        },
        "denominator_diagnostics": denominator,
        "coverage_thresholds": {
            "GOOD": ">= 0.95",
            "USABLE_WITH_COVERAGE_FLAG": ">= 0.80 and < 0.95",
            "POOR": "< 0.80",
        },
        "landscape_annual_series": landscape_series,
        "coverage_status_summary": {
            "object_year_count": len(all_records),
            "GOOD": status_counts["GOOD"],
            "USABLE_WITH_COVERAGE_FLAG": status_counts["USABLE_WITH_COVERAGE_FLAG"],
            "POOR": status_counts["POOR"],
            "zero_valid_object_year_count": zero_valid,
            "by_year": status_by_year,
            "completeness_reference_reconciliation": reconciliation,
        },
        "largest_five_objects": largest_five,
        "object_count": 80,
        "years": list(YEARS),
        "outputs": {
            "disturbance_timeseries": str(timeseries_path),
            "recovery_rasters": [str(rasters_dir / f"recovery_{year}.tif") for year in YEARS],
            "qa_pngs": [str(path) for path in sorted(qa_dir.glob("*.png"))],
        },
        "limitations": [
            "Missing annual NBR pixels are nodata and are not interpolated or spatially filled.",
            (
                "POOR object-years retain raw numerical statistics but are not equally "
                "reliable for reporting."
            ),
            (
                "Recovery is spectral movement toward the 2017 NBR baseline, not ecological "
                "recovery or restored equivalence."
            ),
            "Later annual retained-footprint coverage is incomplete, especially for some "
            "object-years.",
            "No causal attribution is made from these spectral statistics.",
        ],
    }
    summary_path = output_root / "recovery-summary.json"
    summary_path.write_text(
        json.dumps(ensure_json_safe(summary), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--annual-root", type=Path, default=ANNUAL_ROOT)
    parser.add_argument("--disturbance-root", type=Path, default=DISTURBANCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    summary = build(args.config, args.annual_root, args.disturbance_root, args.output_root)
    print(f"Wrote local recovery analysis to {args.output_root}")
    print(
        f"Objects: {summary['object_count']}; years: {len(summary['years'])}; "
        f"canonical inputs unchanged: {summary['canonical_inputs_unchanged']}"
    )


if __name__ == "__main__":
    main()
