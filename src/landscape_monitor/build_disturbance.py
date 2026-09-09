"""Build reproducible 2017--2018 vegetation-disturbance objects.

This module consumes the aligned prototype rasters.  It deliberately does not
query STAC, rebuild composites, or apply morphological cleanup.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from matplotlib import pyplot as plt
from matplotlib.colors import ListedColormap, Normalize
from rasterio.features import shapes
from rasterio.transform import Affine, xy
from rasterio.warp import transform_geom
from scipy import ndimage
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from .composite_prototype import (
    ANALYSIS_CRS,
    ANALYSIS_RESOLUTION,
    PIXEL_AREA_HECTARES,
    AnalysisGrid,
    create_analysis_grid,
)
from .config import ProjectConfig, load_config

OUTPUT_DIR = Path("data/derived/disturbance")
PROTOTYPE_DIR = Path("data/derived/prototype")
RASTER_NAMES = {
    "nbr_2017": "nbr_2017.tif",
    "nbr_2018": "nbr_2018.tif",
    "dnbr_2017_2018": "dnbr_2017_2018.tif",
}
DNBR_SENSITIVITY = (0.25, 0.30, 0.35, 0.40)
BASELINE_SENSITIVITY = (0.20, 0.30, 0.40)
PATCH_SENSITIVITY = (1.0, 2.0, 5.0, 10.0)


def _require_supported_connectivity(connectivity: int) -> None:
    if connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")


def candidate_mask(
    nbr_2017: np.ndarray,
    dnbr_values: np.ndarray,
    baseline_nbr_min: float,
    dnbr_min: float,
    valid_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Return the strict project-specific candidate disturbance mask."""
    baseline = np.asarray(nbr_2017, dtype=np.float32)
    change = np.asarray(dnbr_values, dtype=np.float32)
    if baseline.shape != change.shape:
        raise ValueError("NBR_2017 and dNBR arrays must have the same shape")
    valid = np.isfinite(baseline) & np.isfinite(change)
    if valid_mask is not None:
        valid_array = np.asarray(valid_mask, dtype=bool)
        if valid_array.shape != baseline.shape:
            raise ValueError("valid_mask must have the same shape as input arrays")
        valid &= valid_array
    return valid & (baseline > baseline_nbr_min) & (change >= dnbr_min)


def label_connected_components(mask: np.ndarray, connectivity: int = 8) -> tuple[np.ndarray, int]:
    """Label a binary mask using established 4- or 8-neighbour connectivity."""
    _require_supported_connectivity(connectivity)
    structure = ndimage.generate_binary_structure(2, 2 if connectivity == 8 else 1)
    labels, count = ndimage.label(np.asarray(mask, dtype=bool), structure=structure)
    return labels.astype(np.int32, copy=False), int(count)


def min_pixels_for_area(min_patch_ha: float, pixel_area_ha: float = PIXEL_AREA_HECTARES) -> int:
    """Convert a minimum area into the smallest integer pixel count meeting it."""
    if min_patch_ha <= 0 or pixel_area_ha <= 0:
        raise ValueError("minimum patch area and pixel area must be positive")
    return int(math.ceil(min_patch_ha / pixel_area_ha - 1e-12))


def filter_components(labels: np.ndarray, min_pixels: int) -> tuple[np.ndarray, int, int]:
    """Remove labelled components smaller than ``min_pixels``."""
    if min_pixels <= 0:
        raise ValueError("min_pixels must be positive")
    labels_array = np.asarray(labels)
    if labels_array.ndim != 2:
        raise ValueError("labels must be a two-dimensional array")
    counts = np.bincount(labels_array.ravel())
    retained_raw = np.flatnonzero(counts >= min_pixels)
    retained_raw = retained_raw[retained_raw != 0]
    retained = np.isin(labels_array, retained_raw)
    filtered = np.where(retained, labels_array, 0).astype(np.int32, copy=False)
    component_count = int(max(0, len(counts) - 1))
    return filtered, component_count, int(retained_raw.size)


def _pixel_centroids(
    rows: np.ndarray, columns: np.ndarray, transform: Affine
) -> tuple[float, float]:
    x_values, y_values = xy(transform, rows, columns, offset="center")
    return float(np.mean(x_values)), float(np.mean(y_values))


def touches_aoi_boundary(component_mask: np.ndarray, aoi_mask: np.ndarray) -> bool:
    """Detect a component adjacent to the rasterized analysis-AOI boundary."""
    component = np.asarray(component_mask, dtype=bool)
    aoi = np.asarray(aoi_mask, dtype=bool)
    if component.shape != aoi.shape:
        raise ValueError("component_mask and aoi_mask must have the same shape")
    outside_neighbor = ndimage.maximum_filter(
        (~aoi).astype(np.uint8), size=3, mode="constant", cval=1
    ).astype(bool)
    return bool(np.any(component & outside_neighbor))


def component_statistics(
    labels: np.ndarray,
    nbr_2017: np.ndarray,
    nbr_2018: np.ndarray,
    dnbr_values: np.ndarray,
    transform: Affine,
    aoi_mask: np.ndarray,
    pixel_area_ha: float = PIXEL_AREA_HECTARES,
) -> list[dict[str, Any]]:
    """Calculate object statistics directly from pixels carrying each label."""
    label_array = np.asarray(labels)
    arrays = [np.asarray(nbr_2017), np.asarray(nbr_2018), np.asarray(dnbr_values)]
    if (
        any(array.shape != label_array.shape for array in arrays)
        or np.asarray(aoi_mask).shape != label_array.shape
    ):
        raise ValueError("label and statistic arrays must share a shape")

    records: list[dict[str, Any]] = []
    for raw_label in (int(value) for value in np.unique(label_array) if value > 0):
        rows, columns = np.where(label_array == raw_label)
        if not rows.size:
            continue
        pre_values = arrays[0][rows, columns].astype(np.float64)
        post_values = arrays[1][rows, columns].astype(np.float64)
        change_values = arrays[2][rows, columns].astype(np.float64)
        if not all(
            np.all(np.isfinite(values)) for values in (pre_values, post_values, change_values)
        ):
            raise ValueError(f"component label {raw_label} contains non-finite statistic pixels")
        centroid_x, centroid_y = _pixel_centroids(rows, columns, transform)
        records.append(
            {
                "raw_label": raw_label,
                "pixel_count": int(rows.size),
                "area_ha": float(rows.size * pixel_area_ha),
                "centroid_x": centroid_x,
                "centroid_y": centroid_y,
                "touches_aoi_boundary": touches_aoi_boundary(
                    label_array == raw_label, np.asarray(aoi_mask, dtype=bool)
                ),
                "nbr_2017_mean": float(np.mean(pre_values)),
                "nbr_2017_median": float(np.median(pre_values)),
                "nbr_2018_mean": float(np.mean(post_values)),
                "nbr_2018_median": float(np.median(post_values)),
                "dnbr_mean": float(np.mean(change_values)),
                "dnbr_median": float(np.median(change_values)),
                "dnbr_p90": float(np.percentile(change_values, 90)),
                "dnbr_max": float(np.max(change_values)),
            }
        )
    return records


def deterministic_relabel(
    labels: np.ndarray, records: list[dict[str, Any]]
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Assign stable labels and IDs ordered by area, then centroid coordinates."""
    ordered = sorted(
        records,
        key=lambda record: (
            -record["area_ha"],
            record["centroid_x"],
            record["centroid_y"],
            record["raw_label"],
        ),
    )
    raw_to_stable = {record["raw_label"]: index for index, record in enumerate(ordered, 1)}
    stable_labels = np.zeros(np.asarray(labels).shape, dtype=np.int32)
    for raw_label, stable_label in raw_to_stable.items():
        stable_labels[np.asarray(labels) == raw_label] = stable_label
    stable_records: list[dict[str, Any]] = []
    for stable_label, record in enumerate(ordered, 1):
        stable_record = dict(record)
        stable_record["component_label"] = stable_label
        stable_record["disturbance_id"] = f"disturbance-{stable_label:03d}"
        stable_records.append(stable_record)
    return stable_labels, stable_records


def polygonize_components(labels: np.ndarray, transform: Affine) -> dict[int, Any]:
    """Polygonize labels and union fragments so each component has one geometry."""
    grouped: dict[int, list[Any]] = {}
    label_array = np.asarray(labels, dtype=np.int32)
    for geometry, value in shapes(label_array, mask=label_array > 0, transform=transform):
        grouped.setdefault(int(value), []).append(shape(geometry))
    geometries: dict[int, Any] = {}
    for label in sorted(grouped):
        geometry = unary_union(grouped[label])
        if not geometry.is_valid:
            try:
                from shapely import make_valid

                geometry = make_valid(geometry)
            except ImportError:
                geometry = geometry.buffer(0)
        geometries[label] = geometry
    return geometries


def to_wgs84_geometry(geometry: Any, source_crs: str = ANALYSIS_CRS) -> dict[str, Any]:
    """Transform an analysis-CRS geometry to rounded WGS84 GeoJSON geometry."""
    return transform_geom(source_crs, "EPSG:4326", mapping(geometry), precision=7)


def _geometry_coordinate_count(coordinates: Any) -> int:
    if not isinstance(coordinates, (list, tuple)):
        return 0
    if coordinates and isinstance(coordinates[0], (int, float)):
        return 1
    return sum(_geometry_coordinate_count(value) for value in coordinates)


def geometry_coordinate_count(geometry: dict[str, Any]) -> int:
    return _geometry_coordinate_count(geometry.get("coordinates", []))


def _component_result(
    pre_nbr: np.ndarray,
    change: np.ndarray,
    valid_analysis: np.ndarray,
    baseline_threshold: float,
    dnbr_threshold: float,
    min_patch_ha: float,
    connectivity: int,
    transform: Affine,
    aoi_mask: np.ndarray,
    post_nbr: np.ndarray | None = None,
    pixel_area_ha: float = PIXEL_AREA_HECTARES,
) -> dict[str, Any]:
    candidate = candidate_mask(
        pre_nbr,
        change,
        baseline_threshold,
        dnbr_threshold,
        valid_mask=valid_analysis,
    )
    raw_labels, raw_count = label_connected_components(candidate, connectivity)
    min_pixels = min_pixels_for_area(min_patch_ha, pixel_area_ha)
    filtered_labels, _, retained_count = filter_components(raw_labels, min_pixels)
    retained_pixels = int(np.count_nonzero(filtered_labels))
    counts = np.bincount(filtered_labels.ravel())
    largest_pixels = int(np.max(counts[1:])) if counts.size > 1 else 0
    return {
        "candidate": candidate,
        "raw_labels": raw_labels,
        "filtered_labels": filtered_labels,
        "raw_count": raw_count,
        "raw_pixel_count": int(np.count_nonzero(candidate)),
        "raw_area_ha": float(np.count_nonzero(candidate) * pixel_area_ha),
        "retained_count": retained_count,
        "retained_pixel_count": retained_pixels,
        "retained_area_ha": float(retained_pixels * pixel_area_ha),
        "largest_component_area_ha": float(largest_pixels * pixel_area_ha),
        "min_pixels": min_pixels,
        "records": component_statistics(
            filtered_labels,
            pre_nbr,
            pre_nbr if post_nbr is None else post_nbr,
            change,
            transform,
            aoi_mask,
            pixel_area_ha,
        )
        if post_nbr is not None
        else [],
    }


def sensitivity_analysis(
    pre_nbr: np.ndarray,
    change: np.ndarray,
    valid_analysis: np.ndarray,
    transform: Affine,
    aoi_mask: np.ndarray,
    baseline_default: float,
    dnbr_default: float,
    min_patch_default: float,
    connectivity: int,
    pixel_area_ha: float = PIXEL_AREA_HECTARES,
) -> dict[str, list[dict[str, Any]]]:
    """Run the three requested one-dimensional parameter sensitivities."""

    def result_record(result: dict[str, Any], **parameters: Any) -> dict[str, Any]:
        return {
            **parameters,
            "raw_area_ha": result["raw_area_ha"],
            "retained_area_ha": result["retained_area_ha"],
            "retained_component_count": result["retained_count"],
            "largest_component_area_ha": result["largest_component_area_ha"],
            "components_before_filtering": result["raw_count"],
        }

    dnbr_results = []
    for threshold in DNBR_SENSITIVITY:
        result = _component_result(
            pre_nbr,
            change,
            valid_analysis,
            baseline_default,
            threshold,
            min_patch_default,
            connectivity,
            transform,
            aoi_mask,
            pixel_area_ha=pixel_area_ha,
        )
        dnbr_results.append(result_record(result, dnbr_min=threshold))

    baseline_results = []
    for threshold in BASELINE_SENSITIVITY:
        result = _component_result(
            pre_nbr,
            change,
            valid_analysis,
            threshold,
            dnbr_default,
            min_patch_default,
            connectivity,
            transform,
            aoi_mask,
            pixel_area_ha=pixel_area_ha,
        )
        baseline_results.append(result_record(result, baseline_nbr_min=threshold))

    patch_results = []
    for min_patch in PATCH_SENSITIVITY:
        result = _component_result(
            pre_nbr,
            change,
            valid_analysis,
            baseline_default,
            dnbr_default,
            min_patch,
            connectivity,
            transform,
            aoi_mask,
            pixel_area_ha=pixel_area_ha,
        )
        patch_results.append(result_record(result, min_patch_ha=min_patch))
    return {
        "dnbr_threshold": dnbr_results,
        "baseline_nbr_threshold": baseline_results,
        "minimum_patch_ha": patch_results,
    }


def _expected_grid(config: ProjectConfig) -> AnalysisGrid:
    grid = create_analysis_grid(config.aoi)
    if grid.crs != ANALYSIS_CRS or grid.resolution != ANALYSIS_RESOLUTION:
        raise ValueError("configured analysis grid does not match the prototype grid definition")
    return grid


def _validate_dataset_grid(
    dataset: rasterio.DatasetReader, expected: AnalysisGrid, path: Path
) -> None:
    if dataset.crs is None or dataset.crs.to_string() != ANALYSIS_CRS:
        raise ValueError(
            f"Input raster {path} has unexpected CRS {dataset.crs}; expected {ANALYSIS_CRS}"
        )
    if dataset.width != expected.width or dataset.height != expected.height:
        raise ValueError(
            f"Input raster {path} has dimensions {dataset.width}x{dataset.height}; "
            f"expected {expected.width}x{expected.height}"
        )
    if not np.isclose(dataset.res[0], ANALYSIS_RESOLUTION) or not np.isclose(
        dataset.res[1], ANALYSIS_RESOLUTION
    ):
        raise ValueError(f"Input raster {path} has resolution {dataset.res}; expected 20 m")
    if not np.allclose(tuple(dataset.transform), tuple(expected.transform), rtol=0, atol=1e-9):
        raise ValueError(f"Input raster {path} has a transform different from the prototype grid")


def load_prototype_arrays(
    prototype_dir: Path, config: ProjectConfig
) -> tuple[AnalysisGrid, dict[str, np.ndarray], dict[str, Path]]:
    """Read required prototype rasters and fail explicitly on grid mismatch."""
    grid = _expected_grid(config)
    arrays: dict[str, np.ndarray] = {}
    paths: dict[str, Path] = {}
    for name, filename in RASTER_NAMES.items():
        path = prototype_dir / filename
        paths[name] = path
        if not path.exists():
            raise FileNotFoundError(f"Required prototype input is missing: {path}")
        with rasterio.open(path) as dataset:
            _validate_dataset_grid(dataset, grid, path)
            values = dataset.read(1, masked=False).astype(np.float32)
            if dataset.nodata is not None:
                values[values == dataset.nodata] = np.nan
            values[~np.isfinite(values)] = np.nan
            arrays[name] = values
    return grid, arrays, paths


def _write_integer_raster(
    path: Path, values: np.ndarray, grid: AnalysisGrid, dtype: str, nodata: int
) -> None:
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
        "zlevel": 6,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(values, 1)


def _plot_boundaries(
    axis: Any, geometries: dict[int, Any], records: list[dict[str, Any]], label_count: int = 5
) -> None:
    record_by_label = {record["component_label"]: record for record in records}
    largest_labels = {record["component_label"] for record in records[:label_count]}
    for label in sorted(geometries):
        geometry = geometries[label]
        record = record_by_label[label]
        color = "#00ffff" if record["touches_aoi_boundary"] else "#ffea00"
        linewidth = 1.3 if label in largest_labels else 0.55
        polygons = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
        for polygon in polygons:
            x_values, y_values = polygon.exterior.xy
            axis.plot(x_values, y_values, color=color, linewidth=linewidth)
            for interior in polygon.interiors:
                x_values, y_values = interior.xy
                axis.plot(x_values, y_values, color=color, linewidth=linewidth * 0.7)
        if label in largest_labels:
            axis.text(
                record["centroid_x"],
                record["centroid_y"],
                record["disturbance_id"],
                color="black",
                fontsize=7,
                bbox={"facecolor": "white", "alpha": 0.65, "pad": 1.2, "edgecolor": "none"},
            )


def _plot_mask(path: Path, values: np.ndarray, grid: AnalysisGrid, title: str) -> None:
    figure, axis = plt.subplots(figsize=(10, 7), constrained_layout=True)
    image = axis.imshow(
        np.ma.masked_where(~grid.aoi_mask, values),
        origin="upper",
        extent=grid.bounds,
        cmap=ListedColormap(["#f0f0f0", "#d7301f"]),
        vmin=0,
        vmax=1,
        interpolation="nearest",
    )
    _plot_common_axis(axis, grid, title)
    figure.colorbar(image, ax=axis, ticks=[0.25, 0.75], label="candidate pixel")
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _plot_overlay(
    path: Path,
    values: np.ndarray,
    grid: AnalysisGrid,
    title: str,
    cmap: str,
    geometries: dict[int, Any],
    records: list[dict[str, Any]],
    dnbr_background: bool = False,
) -> None:
    masked = np.ma.masked_where(~np.isfinite(values) | ~grid.aoi_mask, values)
    finite = masked.compressed()
    if dnbr_background:
        limit = max(0.5, float(np.percentile(np.abs(finite), 99)) if finite.size else 0.5)
        norm = Normalize(vmin=-limit, vmax=limit)
    else:
        norm = Normalize(vmin=-0.5, vmax=1.0)
    figure, axis = plt.subplots(figsize=(10, 7), constrained_layout=True)
    image = axis.imshow(masked, origin="upper", extent=grid.bounds, cmap=cmap, norm=norm)
    _plot_boundaries(axis, geometries, records)
    _plot_common_axis(axis, grid, title)
    figure.colorbar(image, ax=axis, label="dNBR" if dnbr_background else "NBR")
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _plot_common_axis(axis: Any, grid: AnalysisGrid, title: str) -> None:
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


def _json_float(value: float) -> float:
    return float(round(value, 8))


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "disturbance_id",
        "component_label",
        "area_ha",
        "pixel_count",
        "centroid_x",
        "centroid_y",
        "touches_aoi_boundary",
        "nbr_2017_mean",
        "nbr_2017_median",
        "nbr_2018_mean",
        "nbr_2018_median",
        "dnbr_mean",
        "dnbr_median",
        "dnbr_p90",
        "dnbr_max",
    )
    result: dict[str, Any] = {}
    for field in fields:
        value = record[field]
        result[field] = _json_float(value) if isinstance(value, float) else value
    return result


def build(config_path: Path, prototype_dir: Path, output_dir: Path) -> dict[str, Any]:
    config = load_config(config_path)
    grid, arrays, source_paths = load_prototype_arrays(prototype_dir, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    pre_nbr = arrays["nbr_2017"]
    post_nbr = arrays["nbr_2018"]
    change = arrays["dnbr_2017_2018"]
    valid_analysis = np.isfinite(pre_nbr) & np.isfinite(change) & grid.aoi_mask
    candidate = candidate_mask(
        pre_nbr,
        change,
        config.baseline_nbr_min,
        config.dnbr_min,
        valid_mask=valid_analysis,
    )
    raw_labels, components_before = label_connected_components(candidate, config.connectivity)
    min_pixels = min_pixels_for_area(config.min_patch_ha)
    filtered_raw_labels, _, components_retained = filter_components(raw_labels, min_pixels)
    records = component_statistics(
        filtered_raw_labels, pre_nbr, post_nbr, change, grid.transform, grid.aoi_mask
    )
    stable_labels, records = deterministic_relabel(filtered_raw_labels, records)
    geometries = polygonize_components(stable_labels, grid.transform)
    if set(geometries) != {record["component_label"] for record in records}:
        raise ValueError("polygonization did not preserve one geometry per retained component")

    retained_pixels = int(np.count_nonzero(stable_labels))
    raw_pixels = int(np.count_nonzero(candidate))
    valid_pixels = int(np.count_nonzero(valid_analysis))
    polygon_area_m2 = float(sum(geometry.area for geometry in geometries.values()))
    raster_area_m2 = retained_pixels * ANALYSIS_RESOLUTION * ANALYSIS_RESOLUTION
    area_difference_m2 = polygon_area_m2 - raster_area_m2

    _write_integer_raster(
        output_dir / "disturbance_mask.tif",
        np.where(grid.aoi_mask, stable_labels > 0, 255).astype(np.uint8),
        grid,
        "uint8",
        255,
    )
    _write_integer_raster(
        output_dir / "disturbance_labels.tif",
        np.where(grid.aoi_mask, stable_labels, 0).astype(np.uint32),
        grid,
        "uint32",
        0,
    )

    features: list[dict[str, Any]] = []
    for record in records:
        geometry = to_wgs84_geometry(geometries[record["component_label"]])
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": _public_record(record),
            }
        )
    geojson = {"type": "FeatureCollection", "features": features}
    geojson_path = output_dir / "disturbances.geojson"
    geojson_path.write_text(json.dumps(geojson, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total_coordinates = sum(geometry_coordinate_count(feature["geometry"]) for feature in features)

    sensitivity = sensitivity_analysis(
        pre_nbr,
        change,
        valid_analysis,
        grid.transform,
        grid.aoi_mask,
        config.baseline_nbr_min,
        config.dnbr_min,
        config.min_patch_ha,
        config.connectivity,
    )

    candidate_plot_values = candidate.astype(np.uint8)
    retained_plot_values = (stable_labels > 0).astype(np.uint8)
    _plot_mask(
        output_dir / "candidate_disturbance_mask.png",
        candidate_plot_values,
        grid,
        "Candidate vegetation disturbance — before component filtering",
    )
    _plot_mask(
        output_dir / "retained_disturbance_mask.png",
        retained_plot_values,
        grid,
        f"Retained vegetation disturbance — minimum patch {config.min_patch_ha:g} ha",
    )
    _plot_overlay(
        output_dir / "dnbr_retained_boundaries.png",
        change,
        grid,
        "dNBR with retained disturbance boundaries",
        "RdBu_r",
        geometries,
        records,
        dnbr_background=True,
    )
    _plot_overlay(
        output_dir / "nbr_2018_retained_boundaries.png",
        post_nbr,
        grid,
        "2018 NBR with retained disturbance boundaries",
        "YlGn",
        geometries,
        records,
    )

    prototype_summary_path = prototype_dir / "prototype-summary.json"
    if not prototype_summary_path.exists():
        raise FileNotFoundError(
            f"Required prototype provenance summary is missing: {prototype_summary_path}"
        )
    prototype_summary = json.loads(prototype_summary_path.read_text(encoding="utf-8"))
    object_records = [_public_record(record) for record in records]
    removed_pixels = raw_pixels - retained_pixels
    summary: dict[str, Any] = {
        "method": "major detected vegetation disturbance objects from 2017–2018 NBR change",
        "interpretation_note": (
            "This is a project-specific disturbance rule, not a universal burn-severity "
            "classification or authoritative fire perimeter."
        ),
        "source_rasters": {name: str(path) for name, path in source_paths.items()},
        "prototype_provenance": {
            "summary_path": str(prototype_summary_path),
            "prototype": prototype_summary.get("prototype"),
            "prototype_summary_reference": (
                "Existing validated 2017/2018 August composite summary; composites were not "
                "recomputed."
            ),
        },
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
            "valid_analysis_pixel_count": valid_pixels,
            "valid_analysis_area_ha": float(valid_pixels * PIXEL_AREA_HECTARES),
            "pixel_area_hectares": PIXEL_AREA_HECTARES,
        },
        "configured_rule": {
            "baseline_nbr_min": config.baseline_nbr_min,
            "baseline_condition": "NBR_2017 > configured baseline_nbr_min",
            "dnbr_min": config.dnbr_min,
            "dnbr_condition": "dNBR >= configured dnbr_min",
            "min_patch_ha": config.min_patch_ha,
            "min_patch_pixels": min_pixels,
            "connectivity": config.connectivity,
            "morphological_cleanup": "none",
        },
        "candidate": {
            "raw_candidate_pixel_count": raw_pixels,
            "raw_candidate_area_ha": float(raw_pixels * PIXEL_AREA_HECTARES),
            "raw_candidate_percentage_of_valid_analysis_area": float(
                100 * raw_pixels / valid_pixels
            )
            if valid_pixels
            else 0.0,
        },
        "components": {
            "before_filtering": components_before,
            "retained": components_retained,
            "removed": components_before - components_retained,
            "removed_area_ha": float(removed_pixels * PIXEL_AREA_HECTARES),
            "retained_pixel_count": retained_pixels,
            "retained_area_ha": float(retained_pixels * PIXEL_AREA_HECTARES),
            "largest_retained_component_area_ha": records[0]["area_ha"] if records else 0.0,
            "median_retained_component_area_ha": float(
                np.median([record["area_ha"] for record in records])
            )
            if records
            else 0.0,
            "touching_aoi_boundary": int(sum(record["touches_aoi_boundary"] for record in records)),
            "retained_percentage_of_valid_analysis_area": float(
                100 * retained_pixels / valid_pixels
            )
            if valid_pixels
            else 0.0,
        },
        "objects": object_records,
        "deterministic_object_ids": [record["disturbance_id"] for record in records],
        "polygon_output": {
            "path": str(geojson_path),
            "crs": "EPSG:4326",
            "feature_count": len(features),
            "file_size_bytes": geojson_path.stat().st_size,
            "total_coordinate_count": total_coordinates,
        },
        "area_consistency": {
            "retained_raster_pixel_area_m2": raster_area_m2,
            "polygon_area_analysis_crs_m2": polygon_area_m2,
            "difference_m2": area_difference_m2,
            "absolute_difference_m2": abs(area_difference_m2),
            "relative_difference": abs(area_difference_m2) / raster_area_m2
            if raster_area_m2
            else 0.0,
            "within_tolerance": bool(abs(area_difference_m2) <= 1.0),
        },
        "sensitivity_analysis": sensitivity,
        "outputs": {
            "rasters": ["disturbance_mask.tif", "disturbance_labels.tif"],
            "geojson": "disturbances.geojson",
            "qa_pngs": [
                "candidate_disturbance_mask.png",
                "retained_disturbance_mask.png",
                "dnbr_retained_boundaries.png",
                "nbr_2018_retained_boundaries.png",
            ],
        },
    }
    summary_path = output_dir / "disturbance-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--prototype-dir", type=Path, default=PROTOTYPE_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    build(args.config, args.prototype_dir, args.output_dir)
    print(f"Wrote disturbance outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
