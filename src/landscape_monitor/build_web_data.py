"""Build the static vector and JSON frontend data package.

This command packages local analytical outputs only.  Disturbance
geometries remain in their original WGS84 topology; the only geometry change
is deterministic longitude/latitude coordinate rounding, gated by area and
validity checks.  No network or raster processing is used.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Callable

from rasterio.warp import transform_geom
from shapely.geometry import shape

ANNUAL_YEARS = list(range(2017, 2027))
BENCHMARK_YEARS = [2017, 2018, 2020, 2023, 2026]
EXPECTED_DISTURBANCE_COUNT = 80
SOURCE_CRS = "EPSG:4326"
AREA_QA_CRS = "EPSG:32633"
PRIMARY_COORDINATE_DECIMALS = 5
FALLBACK_COORDINATE_DECIMALS = 6
TOTAL_AREA_MAX_PERCENT = 0.1
FEATURE_AREA_MAX_PERCENT = 0.5
OVERLAP_AREA_EPSILON_M2 = 1e-7
OUTPUT_FILENAMES = (
    "disturbances.geojson",
    "disturbance-timeseries.json",
    "summary.json",
    "data-manifest.json",
)
SOURCE_RELATIVE_PATHS = {
    "disturbance_geojson": "data/derived/disturbance/disturbances.geojson",
    "disturbance_summary": "data/derived/disturbance/disturbance-summary.json",
    "disturbance_timeseries": "data/derived/recovery/disturbance-timeseries.json",
    "recovery_summary": "data/derived/recovery/recovery-summary.json",
    "annual_completeness": (
        "data/derived/diagnostics/annual-completeness/annual-nbr-completeness.json"
    ),
    "imagery_manifest": "data/derived/web-delivery/imagery-manifest.json",
}


class WebDataBuildError(ValueError):
    """Raised when approved sources or generated package data fail validation."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_paths(repo_root: Path) -> dict[str, Path]:
    return {key: repo_root / value for key, value in SOURCE_RELATIVE_PATHS.items()}


def _output_dir(repo_root: Path) -> Path:
    return repo_root / "data" / "derived" / "web-delivery" / "data"


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise WebDataBuildError(f"could not parse approved source {path}: {exc}") from exc


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_hashes(paths: dict[str, Path]) -> dict[str, str]:
    """Return hashes keyed by project-relative analytical source paths."""
    return {relative: _sha256_file(paths[key]) for key, relative in SOURCE_RELATIVE_PATHS.items()}


def _is_finite_json(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_is_finite_json(item) for item in value.values())
    if isinstance(value, list):
        return all(_is_finite_json(item) for item in value)
    return True


def _require_finite(value: Any, label: str) -> Any:
    if not _is_finite_json(value):
        raise WebDataBuildError(f"{label} contains NaN or Infinity")
    return value


def _round_number(value: Any, decimals: int, label: str) -> Any:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WebDataBuildError(f"{label} must be numeric or null")
    if not math.isfinite(float(value)):
        raise WebDataBuildError(f"{label} contains NaN or Infinity")
    return round(value, decimals)


def _round_coordinates(value: Any, decimals: int) -> Any:
    if isinstance(value, list):
        return [_round_coordinates(item, decimals) for item in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        rounded = round(float(value), decimals)
        return 0.0 if rounded == 0 else rounded
    raise WebDataBuildError("GeoJSON coordinates must contain only numeric values")


def _compact_json_bytes(payload: Any) -> bytes:
    _require_finite(payload, "generated JSON")
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _study_area(repo_root: Path) -> tuple[str, str]:
    with (repo_root / "config" / "project.toml").open("rb") as file:
        config = tomllib.load(file)
    identifier = config["project"]["study_area_id"]
    return identifier, "Kårböle/Ljusdal 2018 wildfire"


def _same_ids(left: list[str], right: list[str], label: str) -> None:
    if len(left) != len(set(left)) or len(right) != len(set(right)) or set(left) != set(right):
        raise WebDataBuildError(f"{label} disturbance IDs do not reconcile")


def _source_context(paths: dict[str, Path]) -> dict[str, Any]:
    """Load and validate all approved source relationships before packaging."""
    geo = _load_json(paths["disturbance_geojson"])
    disturbance_summary = _load_json(paths["disturbance_summary"])
    timeseries = _load_json(paths["disturbance_timeseries"])
    recovery_summary = _load_json(paths["recovery_summary"])
    completeness = _load_json(paths["annual_completeness"])
    imagery_manifest = _load_json(paths["imagery_manifest"])
    for label, value in (
        ("disturbance GeoJSON", geo),
        ("disturbance summary", disturbance_summary),
        ("disturbance time series", timeseries),
        ("recovery summary", recovery_summary),
        ("annual completeness", completeness),
        ("imagery manifest", imagery_manifest),
    ):
        _require_finite(value, label)

    if geo.get("type") != "FeatureCollection":
        raise WebDataBuildError("analytical disturbance GeoJSON is not a FeatureCollection")
    geo_features = geo.get("features", [])
    summary_objects = disturbance_summary.get("objects", [])
    ts_objects = timeseries.get("disturbances", [])
    if len(geo_features) != EXPECTED_DISTURBANCE_COUNT:
        raise WebDataBuildError("analytical disturbance GeoJSON must contain exactly 80 features")
    if len(summary_objects) != EXPECTED_DISTURBANCE_COUNT:
        raise WebDataBuildError("disturbance summary must contain exactly 80 objects")
    if len(ts_objects) != EXPECTED_DISTURBANCE_COUNT:
        raise WebDataBuildError("analytical time series must contain exactly 80 objects")

    geo_ids = [feature["properties"]["disturbance_id"] for feature in geo_features]
    summary_ids = [item["disturbance_id"] for item in summary_objects]
    ts_ids = [item["disturbance_id"] for item in ts_objects]
    _same_ids(geo_ids, summary_ids, "GeoJSON/summary")
    _same_ids(geo_ids, ts_ids, "GeoJSON/time series")
    if geo_ids != sorted(geo_ids) or summary_ids != sorted(summary_ids):
        raise WebDataBuildError("analytical disturbance ordering is not deterministic")

    summary_by_id = {item["disturbance_id"]: item for item in summary_objects}
    ts_by_id = {item["disturbance_id"]: item for item in ts_objects}
    for feature in geo_features:
        identifier = feature["properties"]["disturbance_id"]
        area = feature["properties"].get("area_ha")
        if not math.isclose(area, summary_by_id[identifier]["area_ha"], abs_tol=1e-9):
            raise WebDataBuildError(f"analytical area mismatch for {identifier}")
        if not math.isclose(area, ts_by_id[identifier]["area_ha"], abs_tol=1e-9):
            raise WebDataBuildError(f"analytical time-series area mismatch for {identifier}")

    if timeseries.get("years") != ANNUAL_YEARS:
        raise WebDataBuildError("analytical time series must cover 2017–2026")
    if recovery_summary.get("years") != ANNUAL_YEARS:
        raise WebDataBuildError("recovery summary years do not cover 2017–2026")
    if completeness.get("years") != ANNUAL_YEARS:
        raise WebDataBuildError("annual completeness years do not cover 2017–2026")
    completeness_rows = {
        (item["disturbance_id"], item["year"]): item for item in completeness["disturbances"]
    }
    if len(completeness_rows) != EXPECTED_DISTURBANCE_COUNT * len(ANNUAL_YEARS):
        raise WebDataBuildError("annual completeness must contain exactly 80 × 10 records")
    for item in ts_objects:
        series = item.get("series", [])
        if len(series) != len(ANNUAL_YEARS) or [row["year"] for row in series] != ANNUAL_YEARS:
            raise WebDataBuildError(
                f"{item['disturbance_id']} does not have 2017–2026 exactly once"
            )
        for row in series:
            completeness_row = completeness_rows[item["disturbance_id"], row["year"]]
            if completeness_row["category"] != row["nbr_coverage_status"]:
                raise WebDataBuildError("coverage status differs from annual completeness")
            if not math.isclose(
                completeness_row["valid_fraction"], row["nbr_valid_fraction"], abs_tol=1e-12
            ):
                raise WebDataBuildError("coverage fraction differs from annual completeness")

    if imagery_manifest.get("benchmark_years") != BENCHMARK_YEARS:
        raise WebDataBuildError("benchmark years differ from imagery manifest")
    landscape_series = recovery_summary.get("landscape_annual_series", [])
    if [item["year"] for item in landscape_series] != ANNUAL_YEARS:
        raise WebDataBuildError("recovery landscape annual series is not chronological 2017–2026")
    completeness_landscape = {item["year"]: item for item in completeness["landscape"]}
    for item in landscape_series:
        reference = completeness_landscape[item["year"]]
        if not math.isclose(
            item["valid_nbr_fraction"],
            reference["retained_disturbance_nbr_valid_fraction"],
            abs_tol=1e-12,
        ):
            raise WebDataBuildError("landscape NBR coverage differs from completeness source")

    approved_area = disturbance_summary["components"]["retained_area_ha"]
    summed_area = sum(float(item["area_ha"]) for item in summary_objects)
    if not math.isclose(approved_area, summed_area, abs_tol=1e-9):
        raise WebDataBuildError("retained analytical area does not match disturbance objects")

    return {
        "geo": geo,
        "disturbance_summary": disturbance_summary,
        "timeseries": timeseries,
        "recovery_summary": recovery_summary,
        "completeness": completeness,
        "imagery_manifest": imagery_manifest,
        "summary_by_id": summary_by_id,
        "ts_by_id": ts_by_id,
        "approved_area_ha": approved_area,
    }


def _projected_geometry(geometry: dict[str, Any]):
    projected = transform_geom(SOURCE_CRS, AREA_QA_CRS, geometry, precision=-1)
    return shape(projected)


def _overlap_pairs(geometries: list[Any], identifiers: list[str]) -> list[dict[str, Any]]:
    overlaps = []
    for index, left in enumerate(geometries):
        for other_index in range(index + 1, len(geometries)):
            intersection = left.intersection(geometries[other_index])
            if not intersection.is_empty and intersection.area > OVERLAP_AREA_EPSILON_M2:
                overlaps.append(
                    {
                        "left": identifiers[index],
                        "right": identifiers[other_index],
                        "area_m2": intersection.area,
                    }
                )
    return overlaps


def _rounded_geometry(feature: dict[str, Any], decimals: int) -> dict[str, Any]:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or "type" not in geometry or "coordinates" not in geometry:
        raise WebDataBuildError("analytical feature has no usable geometry")
    return {
        "type": geometry["type"],
        "coordinates": _round_coordinates(geometry["coordinates"], decimals),
    }


def _web_properties(
    source_properties: dict[str, Any],
    time_series: dict[str, Any],
) -> dict[str, Any]:
    return {
        "disturbance_id": source_properties["disturbance_id"],
        "area_ha": _round_number(source_properties.get("area_ha"), 2, "area_ha"),
        "touches_aoi_boundary": source_properties.get("touches_aoi_boundary"),
        "nbr_2017_median": _round_number(
            source_properties.get("nbr_2017_median"), 4, "nbr_2017_median"
        ),
        "nbr_2018_median": _round_number(
            source_properties.get("nbr_2018_median"), 4, "nbr_2018_median"
        ),
        "dnbr_median": _round_number(source_properties.get("dnbr_median"), 4, "dnbr_median"),
        "recovery_2026_median": _round_number(
            time_series.get("recovery_median"), 4, "recovery_2026_median"
        ),
        "recovery_2026_valid_fraction": _round_number(
            time_series.get("recovery_valid_fraction"), 4, "recovery_2026_valid_fraction"
        ),
        "recovery_2026_coverage_status": time_series.get("nbr_coverage_status"),
        "recovery_2026_reporting_recommended": time_series.get(
            "recovery_reporting_recommended"
        ),
    }


def _web_features(context: dict[str, Any], decimals: int) -> list[dict[str, Any]]:
    features = []
    for source_feature in sorted(
        context["geo"]["features"], key=lambda item: item["properties"]["disturbance_id"]
    ):
        identifier = source_feature["properties"]["disturbance_id"]
        row_2026 = next(
            row for row in context["ts_by_id"][identifier]["series"] if row["year"] == 2026
        )
        features.append(
            {
                "type": "Feature",
                "geometry": _rounded_geometry(source_feature, decimals),
                "properties": _web_properties(source_feature["properties"], row_2026),
            }
        )
    return features


def geometry_qa(
    source_features: list[dict[str, Any]],
    rounded_features: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate rounded geometry without editing or repairing it."""
    source_ids = [feature["properties"]["disturbance_id"] for feature in source_features]
    rounded_ids = [feature["properties"]["disturbance_id"] for feature in rounded_features]
    if source_ids != rounded_ids:
        raise WebDataBuildError("coordinate rounding changed disturbance IDs or feature ordering")
    if len(rounded_features) != EXPECTED_DISTURBANCE_COUNT:
        raise WebDataBuildError("rounded GeoJSON must contain exactly 80 features")

    source_projected = [_projected_geometry(feature["geometry"]) for feature in source_features]
    rounded_projected = [_projected_geometry(feature["geometry"]) for feature in rounded_features]
    invalid = []
    geometry_type_mismatches = []
    area_differences = []
    for source_feature, rounded_feature, source_geometry, rounded_geometry in zip(
        source_features, rounded_features, source_projected, rounded_projected, strict=True
    ):
        identifier = source_feature["properties"]["disturbance_id"]
        source_type = source_feature["geometry"]["type"]
        rounded_type = rounded_feature["geometry"]["type"]
        if source_type != rounded_type or rounded_type not in {"Polygon", "MultiPolygon"}:
            geometry_type_mismatches.append(identifier)
        if rounded_geometry.is_empty or not rounded_geometry.is_valid:
            invalid.append(identifier)
        source_area = source_geometry.area
        rounded_area = rounded_geometry.area
        area_differences.append(100.0 * (rounded_area - source_area) / source_area)

    source_overlaps = _overlap_pairs(source_projected, source_ids)
    rounded_overlaps = _overlap_pairs(rounded_projected, rounded_ids)
    source_overlap_keys = {(item["left"], item["right"]) for item in source_overlaps}
    new_overlaps = [
        item
        for item in rounded_overlaps
        if (item["left"], item["right"]) not in source_overlap_keys
    ]
    total_source_area = sum(geometry.area for geometry in source_projected)
    total_rounded_area = sum(geometry.area for geometry in rounded_projected)
    total_difference = 100.0 * (total_rounded_area - total_source_area) / total_source_area
    max_absolute = max(abs(value) for value in area_differences)
    median_absolute = sorted(abs(value) for value in area_differences)[len(area_differences) // 2]
    passes = (
        not invalid
        and not geometry_type_mismatches
        and not new_overlaps
        and abs(total_difference) <= TOTAL_AREA_MAX_PERCENT
        and max_absolute <= FEATURE_AREA_MAX_PERCENT
    )
    return {
        "passes": passes,
        "feature_count": len(rounded_features),
        "invalid_features": invalid,
        "geometry_type_mismatches": geometry_type_mismatches,
        "source_overlaps": source_overlaps,
        "rounded_overlaps": rounded_overlaps,
        "new_overlaps": new_overlaps,
        "total_source_area_ha": total_source_area / 10000.0,
        "total_rounded_area_ha": total_rounded_area / 10000.0,
        "total_area_difference_percent": total_difference,
        "maximum_absolute_feature_area_difference_percent": max_absolute,
        "median_absolute_feature_area_difference_percent": median_absolute,
        "per_feature_area_difference_percent": dict(zip(source_ids, area_differences, strict=True)),
    }


def choose_coordinate_precision(
    context: dict[str, Any],
    qa_function: Callable[
        [list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]
    ] = geometry_qa,
) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
    """Use five decimals, retry once at six, and fail rather than transform geometry."""
    source_features = sorted(
        context["geo"]["features"], key=lambda item: item["properties"]["disturbance_id"]
    )
    attempts = []
    for decimals in (PRIMARY_COORDINATE_DECIMALS, FALLBACK_COORDINATE_DECIMALS):
        features = _web_features(context, decimals)
        qa = qa_function(source_features, features)
        attempts.append((decimals, qa))
        if qa["passes"]:
            return decimals, features, qa
    details = "; ".join(
        f"{decimals} decimals: total={qa['total_area_difference_percent']:.6f}%, "
        f"max={qa['maximum_absolute_feature_area_difference_percent']:.6f}%, "
        f"invalid={qa['invalid_features']}, new_overlaps={qa['new_overlaps']}"
        for decimals, qa in attempts
    )
    raise WebDataBuildError(
        f"coordinate rounding QA failed at both permitted precisions: {details}"
    )


def _time_series_payload(context: dict[str, Any]) -> dict[str, Any]:
    disturbances = {}
    for identifier in sorted(context["ts_by_id"]):
        source_object = context["ts_by_id"][identifier]
        disturbances[identifier] = {
            "area_ha": _round_number(source_object["area_ha"], 2, f"{identifier}.area_ha"),
            "series": [
                {
                    "year": row["year"],
                    "nbr_median": _round_number(row.get("nbr_median"), 4, "nbr_median"),
                    "recovery_median": _round_number(
                        row.get("recovery_median"), 4, "recovery_median"
                    ),
                    "recovery_p10": _round_number(row.get("recovery_p10"), 4, "recovery_p10"),
                    "recovery_p90": _round_number(row.get("recovery_p90"), 4, "recovery_p90"),
                    "nbr_valid_fraction": _round_number(
                        row.get("nbr_valid_fraction"), 4, "nbr_valid_fraction"
                    ),
                    "coverage_status": row.get("nbr_coverage_status"),
                    "reporting_recommended": row.get("recovery_reporting_recommended"),
                    "ndvi_median": _round_number(row.get("ndvi_median"), 4, "ndvi_median"),
                    "ndvi_valid_fraction": _round_number(
                        row.get("ndvi_valid_fraction"), 4, "ndvi_valid_fraction"
                    ),
                }
                for row in source_object["series"]
            ],
        }
    return {
        "schema_version": 1,
        "years": ANNUAL_YEARS,
        "coverage_thresholds": {"good_min": 0.95, "usable_min": 0.80},
        "disturbances": disturbances,
    }


def _summary_payload(context: dict[str, Any], study_area: tuple[str, str]) -> dict[str, Any]:
    recovery_summary = context["recovery_summary"]
    coverage_by_year = {
        item["year"]: item for item in recovery_summary["coverage_status_summary"]["by_year"]
    }
    annual = []
    for item in recovery_summary["landscape_annual_series"]:
        annual.append(
            {
                "year": item["year"],
                "nbr_median": _round_number(item.get("nbr_median"), 4, "summary.nbr_median"),
                "recovery_median": _round_number(
                    item.get("recovery_median"), 4, "summary.recovery_median"
                ),
                "recovery_p10": _round_number(item.get("recovery_p10"), 4, "summary.recovery_p10"),
                "recovery_p90": _round_number(item.get("recovery_p90"), 4, "summary.recovery_p90"),
                "nbr_valid_fraction": _round_number(
                    item.get("valid_nbr_fraction"), 4, "summary.nbr_valid_fraction"
                ),
                "fraction_ge_050": _round_number(
                    item.get("fraction_ge_050"), 4, "summary.fraction_ge_050"
                ),
                "fraction_ge_080": _round_number(
                    item.get("fraction_ge_080"), 4, "summary.fraction_ge_080"
                ),
                "fraction_ge_100": _round_number(
                    item.get("fraction_ge_100"), 4, "summary.fraction_ge_100"
                ),
                "fraction_lt_000": _round_number(
                    item.get("fraction_lt_000"), 4, "summary.fraction_lt_000"
                ),
                "fraction_gt_100": _round_number(
                    item.get("fraction_gt_100"), 4, "summary.fraction_gt_100"
                ),
                "ndvi_median": _round_number(item.get("ndvi_median"), 4, "summary.ndvi_median"),
                "ndvi_valid_fraction": _round_number(
                    item.get("ndvi_valid_fraction"), 4, "summary.ndvi_valid_fraction"
                ),
            }
        )
    current = next(item for item in annual if item["year"] == 2026)
    return {
        "schema_version": 1,
        "project": {
            "case_study_identifier": study_area[0],
            "case_study_name": study_area[1],
            "annual_years": ANNUAL_YEARS,
            "benchmark_imagery_years": BENCHMARK_YEARS,
            "disturbance_object_count": EXPECTED_DISTURBANCE_COUNT,
            "total_analytical_disturbance_area_ha": _round_number(
                context["approved_area_ha"], 2, "total disturbance area"
            ),
            "primary_indicator": "NBR",
            "secondary_indicator": "NDVI",
            "recovery_metric": "spectral recovery",
        },
        "landscape_annual_series": annual,
        "coverage_by_year": [
            {
                "year": year,
                "GOOD": coverage_by_year[year]["GOOD"],
                "USABLE_WITH_COVERAGE_FLAG": coverage_by_year[year][
                    "USABLE_WITH_COVERAGE_FLAG"
                ],
                "POOR": coverage_by_year[year]["POOR"],
                "zero_valid_count": coverage_by_year[year]["zero_valid_object_count"],
            }
            for year in ANNUAL_YEARS
        ],
        "current_2026": {
            "recovery_median": current["recovery_median"],
            "nbr_valid_fraction": current["nbr_valid_fraction"],
            "fraction_ge_080": current["fraction_ge_080"],
            "fraction_ge_100": current["fraction_ge_100"],
        },
        "limitation_flags": {
            "spectral_not_ecological_recovery": True,
            "later_year_coverage_varies": True,
            "missing_values_interpolated": False,
        },
    }


def _manifest_payload(
    payloads: dict[str, bytes],
    context: dict[str, Any],
    coordinate_decimals: int,
) -> dict[str, Any]:
    file_records = []
    for filename in OUTPUT_FILENAMES[:3]:
        data = payloads[filename]
        file_records.append(
            {
                "path": f"data/{filename}",
                "sha256": _sha256_bytes(data),
                "size_bytes": len(data),
            }
        )
    return {
        "manifest_version": 1,
        "schema_versions": {
            "data-manifest.json": 1,
            "disturbances.geojson": 1,
            "disturbance-timeseries.json": 1,
            "summary.json": 1,
        },
        "files": file_records,
        "counts": {
            "disturbances": EXPECTED_DISTURBANCE_COUNT,
            "annual_years": len(ANNUAL_YEARS),
            "benchmark_years": len(BENCHMARK_YEARS),
        },
        "geojson": {
            "path": "data/disturbances.geojson",
            "crs": SOURCE_CRS,
            "coordinate_decimal_places": coordinate_decimals,
            "geometry_simplification": False,
        },
        "annual_years": ANNUAL_YEARS,
        "benchmark_years": BENCHMARK_YEARS,
        "sources": SOURCE_RELATIVE_PATHS,
        "numeric_rounding": {
            "area_ha": 2,
            "nbr": 4,
            "dnbr": 4,
            "recovery": 4,
            "fractions": 4,
        },
    }


def _validate_output_dir(output_dir: Path, repo_root: Path) -> None:
    candidate = output_dir.resolve()
    forbidden = [
        repo_root / "data" / "derived" / "disturbance",
        repo_root / "data" / "derived" / "recovery",
        repo_root / "data" / "derived" / "diagnostics",
        repo_root / "data" / "derived" / "annual",
    ]
    if any(
        candidate == item.resolve() or item.resolve() in candidate.parents for item in forbidden
    ):
        raise WebDataBuildError("web data output cannot overwrite analytical source directories")
    if candidate.name != "data" or candidate.parent.name != "web-delivery":
        raise WebDataBuildError("web data output must be data/derived/web-delivery/data")


def _write_atomic(output_dir: Path, payloads: dict[str, bytes]) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".web-data-", dir=output_dir.parent) as temporary:
        temporary_dir = Path(temporary)
        for filename, data in payloads.items():
            (temporary_dir / filename).write_bytes(data)
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename in OUTPUT_FILENAMES:
            os.replace(temporary_dir / filename, output_dir / filename)


def gzip_size(data: bytes) -> int:
    """Return a deterministic diagnostic gzip size without writing a .gz asset."""
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as compressed:
        compressed.write(data)
    return len(buffer.getvalue())


def build(repo_root: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    """Build and validate all four package files from local approved sources."""
    root = (repo_root or _repo_root()).resolve()
    target = (output_dir or _output_dir(root)).resolve()
    _validate_output_dir(target, root)
    paths = _source_paths(root)
    before_hashes = source_hashes(paths)
    context = _source_context(paths)
    coordinate_decimals, web_features, geometry_result = choose_coordinate_precision(context)
    web_geojson = {"type": "FeatureCollection", "features": web_features}
    web_timeseries = _time_series_payload(context)
    web_summary = _summary_payload(context, _study_area(root))
    payloads = {
        "disturbances.geojson": _compact_json_bytes(web_geojson),
        "disturbance-timeseries.json": _compact_json_bytes(web_timeseries),
        "summary.json": _compact_json_bytes(web_summary),
    }
    manifest = _manifest_payload(payloads, context, coordinate_decimals)
    payloads["data-manifest.json"] = _compact_json_bytes(manifest)
    after_hashes = source_hashes(paths)
    if before_hashes != after_hashes:
        raise WebDataBuildError("approved analytical source hashes changed during packaging")
    _write_atomic(target, payloads)
    return {
        "output_dir": target,
        "coordinate_decimals": coordinate_decimals,
        "geometry_qa": geometry_result,
        "source_hashes": before_hashes,
        "outputs": {
            filename: {
                "size_bytes": len(data),
                "gzip_size_bytes": gzip_size(data),
                "sha256": _sha256_bytes(data),
            }
            for filename, data in payloads.items()
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    result = build()
    qa = result["geometry_qa"]
    print(f"built static web data in {result['output_dir']}")
    print(f"coordinate decimals: {result['coordinate_decimals']}")
    print(
        "geometry QA: "
        f"total area difference={qa['total_area_difference_percent']:.6f}%, "
        f"max feature difference={qa['maximum_absolute_feature_area_difference_percent']:.6f}%, "
        f"median absolute difference={qa['median_absolute_feature_area_difference_percent']:.6f}%"
    )
    for filename, details in result["outputs"].items():
        print(
            f"{filename}: {details['size_bytes']} bytes, "
            f"gzip diagnostic {details['gzip_size_bytes']} bytes, "
            f"sha256 {details['sha256']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
