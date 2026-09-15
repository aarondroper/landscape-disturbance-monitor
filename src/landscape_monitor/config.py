"""Configuration loading and validation for the landscape monitoring pipeline."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class BBox:
    west: float
    south: float
    east: float
    north: float

    def as_list(self) -> list[float]:
        return [self.west, self.south, self.east, self.north]


@dataclass(frozen=True)
class ProjectConfig:
    study_area_id: str
    aoi: BBox
    analysis_years: tuple[int, ...]
    month: int
    window_start_day: int
    window_end_day: int
    benchmark_years: tuple[int, ...]
    stac_endpoint: str
    collection: str
    baseline_nbr_min: float
    dnbr_min: float
    min_patch_ha: float
    connectivity: int
    visualization_resolution_m: float
    rgb_black_point: float
    rgb_white_point: float
    rgb_gamma: float

    def annual_august_intervals(self) -> dict[int, tuple[str, str]]:
        """Return August search intervals as UTC ISO-8601 strings.

        STAC datetime intervals use an exclusive upper bound here, so August 31
        is included by using September 1 as the end instant.
        """
        intervals: dict[int, tuple[str, str]] = {}
        for year in self.analysis_years:
            start = date(year, self.month, self.window_start_day)
            end = date(year, self.month, self.window_end_day) + timedelta(days=1)
            start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
            end_dt = datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)
            intervals[year] = (
                start_dt.isoformat().replace("+00:00", "Z"),
                end_dt.isoformat().replace("+00:00", "Z"),
            )
        return intervals


def _as_int_tuple(value: object, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
        raise ValueError(f"{field_name} must be a list of integers")
    return tuple(value)


def load_config(path: str | Path) -> ProjectConfig:
    """Load and validate the checked-in TOML project configuration."""
    config_path = Path(path)
    with config_path.open("rb") as file:
        raw = tomllib.load(file)

    project = raw.get("project", {})
    aoi = raw.get("aoi", {})
    temporal = raw.get("temporal", {})
    stac = raw.get("stac", {})
    disturbance = raw.get("disturbance", {})
    visualization = raw.get("visualization", {})
    try:
        bbox = BBox(*(float(aoi[name]) for name in ("west", "south", "east", "north")))
        years = _as_int_tuple(temporal.get("analysis_years"), "analysis_years")
        benchmarks = _as_int_tuple(temporal.get("benchmark_years"), "benchmark_years")
        month = int(temporal["month"])
        start_day = int(temporal["window_start_day"])
        end_day = int(temporal["window_end_day"])
        baseline_nbr_min = float(disturbance["baseline_nbr_min"])
        dnbr_min = float(disturbance["dnbr_min"])
        min_patch_ha = float(disturbance["min_patch_ha"])
        connectivity = int(disturbance["connectivity"])
        visualization_resolution_m = float(visualization["resolution_m"])
        rgb_black_point = float(visualization["rgb_black_point"])
        rgb_white_point = float(visualization["rgb_white_point"])
        rgb_gamma = float(visualization["rgb_gamma"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid configuration in {config_path}") from exc

    if not project.get("study_area_id"):
        raise ValueError("project.study_area_id is required")
    if not (-180 <= bbox.west < bbox.east <= 180 and -90 <= bbox.south < bbox.north <= 90):
        raise ValueError("aoi must be a valid west, south, east, north WGS84 bbox")
    if not years or years != tuple(range(years[0], years[-1] + 1)):
        raise ValueError("analysis_years must be a non-empty contiguous list")
    if any(year not in years for year in benchmarks):
        raise ValueError("benchmark_years must be contained in analysis_years")
    if not 1 <= month <= 12:
        raise ValueError("temporal.month must be between 1 and 12")
    if not 1 <= start_day <= end_day <= 31:
        raise ValueError("temporal window days must be ordered and valid")
    for year in years:
        date(year, month, start_day)
        date(year, month, end_day)
    if not stac.get("endpoint") or not stac.get("collection"):
        raise ValueError("stac.endpoint and stac.collection are required")
    if not -1.0 <= baseline_nbr_min <= 1.0:
        raise ValueError("disturbance.baseline_nbr_min must be between -1 and 1")
    if not -2.0 <= dnbr_min <= 2.0:
        raise ValueError("disturbance.dnbr_min must be between -2 and 2")
    if min_patch_ha <= 0:
        raise ValueError("disturbance.min_patch_ha must be positive")
    if connectivity not in (4, 8):
        raise ValueError("disturbance.connectivity must be 4 or 8")
    if visualization_resolution_m <= 0:
        raise ValueError("visualization.resolution_m must be positive")
    if not 0 <= rgb_black_point < rgb_white_point:
        raise ValueError("visualization RGB black/white points must be ordered")
    if rgb_gamma <= 0:
        raise ValueError("visualization.rgb_gamma must be positive")

    return ProjectConfig(
        study_area_id=str(project["study_area_id"]),
        aoi=bbox,
        analysis_years=years,
        month=month,
        window_start_day=start_day,
        window_end_day=end_day,
        benchmark_years=benchmarks,
        stac_endpoint=str(stac["endpoint"]),
        collection=str(stac["collection"]),
        baseline_nbr_min=baseline_nbr_min,
        dnbr_min=dnbr_min,
        min_patch_ha=min_patch_ha,
        connectivity=connectivity,
        visualization_resolution_m=visualization_resolution_m,
        rgb_black_point=rgb_black_point,
        rgb_white_point=rgb_white_point,
        rgb_gamma=rgb_gamma,
    )
