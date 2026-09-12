"""Sequential, resumable orchestration for explicit annual composites.

The single-year annual builder remains the analytical primitive.  This module
only validates existing annual outputs and launches that builder in one fresh
child Python process at a time.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import rasterio
from rasterio.windows import Window

from .build_annual_series import (
    APPROVED_BOUNDS,
    APPROVED_HEIGHT,
    APPROVED_WIDTH,
    validate_output_grid,
)
from .composite_prototype import ReflectanceTreatment
from .config import ProjectConfig, load_config

ANNUAL_MODULE = "landscape_monitor.build_annual_series"
REQUIRED_OUTPUTS = ("nbr.tif", "ndvi.tif", "valid_count.tif", "annual-summary.json")
ANALYTICAL_RASTERS = ("nbr.tif", "ndvi.tif", "valid_count.tif")
REQUIRED_SUMMARY_PATHS = (
    ("processing_version",),
    ("year",),
    ("requested_interval", "start"),
    ("requested_interval", "end"),
    ("stac_item_count",),
    ("grouped_acquisition_count",),
    ("usable_acquisition_count",),
    ("analysis_grid",),
    ("valid_coverage", "nbr_percent"),
    ("valid_coverage", "ndvi_percent"),
    ("nbr_distribution", "count"),
    ("nbr_distribution", "median"),
    ("nbr_distribution", "min"),
    ("nbr_distribution", "max"),
    ("ndvi_distribution", "count"),
    ("ndvi_distribution", "median"),
    ("ndvi_distribution", "min"),
    ("ndvi_distribution", "max"),
    ("memory_telemetry", "peak_max_rss_mib"),
    ("temporary_storage", "peak_bytes"),
    ("reduction", "block_count"),
    ("outputs", "files"),
)


@dataclass(frozen=True)
class ValidationResult:
    """Metadata-only annual output classification."""

    state: str
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state, "reasons": list(self.reasons)}


def normalize_years(years: Sequence[int], config: ProjectConfig) -> tuple[int, ...]:
    """Validate and deterministically sort a non-empty explicit year set."""
    if not years:
        raise ValueError("at least one explicit year is required via --years")
    if any(not isinstance(year, int) or isinstance(year, bool) for year in years):
        raise ValueError("years must be integers")
    unsupported = sorted(set(years) - set(config.analysis_years))
    if unsupported:
        raise ValueError(
            f"unsupported year(s) {unsupported}; configured years are "
            f"{list(config.analysis_years)}"
        )
    return tuple(sorted(set(years)))


def _missing_summary_path(summary: dict[str, Any], path: tuple[str, ...]) -> bool:
    value: Any = summary
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return True
        value = value[key]
    return False


def _invalid(reason: str) -> ValidationResult:
    return ValidationResult("INVALID", (reason,))


def _validate_summary(
    summary_path: Path, summary: Any, year: int, annual_dir: Path
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(summary, dict):
        return [f"{summary_path} must contain a JSON object"]
    for path in REQUIRED_SUMMARY_PATHS:
        if _missing_summary_path(summary, path):
            reasons.append("summary is missing field " + ".".join(path))

    if summary.get("year") != year:
        reasons.append(f"summary year is {summary.get('year')!r}, expected {year}")

    processing_version = summary.get("processing_version")
    if not isinstance(processing_version, str) or not processing_version.startswith(
        "annual-composite"
    ):
        reasons.append("summary does not identify a completed annual composite build")

    processing = summary.get("processing")
    if not isinstance(processing, dict) or processing.get("temporal_statistic") != (
        "exact per-pixel median across valid acquisition dates"
    ):
        reasons.append("summary does not record the exact temporal median")
    stored_treatment = (
        processing.get("reflectance_treatment") if isinstance(processing, dict) else None
    )
    if stored_treatment is not None and stored_treatment != ReflectanceTreatment.REJECT.value:
        reasons.append(
            "summary records a non-production reflectance treatment: "
            f"{stored_treatment!r}"
        )

    outputs = summary.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}
        reasons.append("summary outputs must be an object")
    output_files = outputs.get("files")
    if isinstance(output_files, dict):
        expected_keys = {"nbr", "ndvi", "valid_count", "summary"}
        missing_keys = sorted(expected_keys - set(output_files))
        if missing_keys:
            reasons.append("summary outputs.files is missing " + ", ".join(missing_keys))

    file_sizes = outputs.get("file_sizes_bytes")
    if isinstance(file_sizes, dict):
        for filename in REQUIRED_OUTPUTS:
            expected_size = file_sizes.get(filename)
            actual_path = annual_dir / filename
            if expected_size is None:
                reasons.append(f"summary outputs.file_sizes_bytes is missing {filename}")
            elif expected_size != actual_path.stat().st_size:
                reasons.append(
                    f"summary size for {filename} is {expected_size}, "
                    f"actual size is {actual_path.stat().st_size}"
                )

    return reasons


def classify_annual_output(
    annual_dir: Path, year: int, config: ProjectConfig
) -> ValidationResult:
    """Classify one annual directory without reading complete raster arrays.

    A missing or empty directory is safe to build.  Once a directory contains
    output material, any missing, malformed, unreadable, or inconsistent
    required output is INVALID and is never removed or overwritten by this
    orchestrator.
    """
    if not annual_dir.exists():
        return ValidationResult("MISSING", ("annual output directory does not exist",))
    if not annual_dir.is_dir():
        return _invalid(f"annual output path {annual_dir} is not a directory")
    if not any(annual_dir.iterdir()):
        return ValidationResult("MISSING", ("annual output directory is empty",))

    paths = {name: annual_dir / name for name in REQUIRED_OUTPUTS}
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        return _invalid("missing required output file(s): " + ", ".join(missing))

    summary_path = paths["annual-summary.json"]
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _invalid(f"annual summary cannot be parsed: {type(exc).__name__}: {exc}")

    reasons = _validate_summary(summary_path, summary, year, annual_dir)

    try:
        from .build_annual_series import _approved_grid

        grid = _approved_grid(config)
    except (OSError, ValueError) as exc:
        return _invalid(f"approved analysis grid cannot be established: {exc}")

    metadata: dict[str, tuple[Any, ...]] = {}
    for filename in ANALYTICAL_RASTERS:
        path = annual_dir / filename
        try:
            with rasterio.open(path) as dataset:
                if dataset.count != 1:
                    reasons.append(f"{path} has {dataset.count} bands, expected 1")
                validate_output_grid(dataset, grid, path)
                if not np.allclose(dataset.res, (20.0, 20.0), atol=1e-9):
                    reasons.append(f"{path} has resolution {dataset.res}, expected (20.0, 20.0)")
                # A one-pixel read verifies that the file is readable without
                # scanning the complete analytical raster.
                dataset.read(1, window=Window(0, 0, 1, 1))
                metadata[filename] = (
                    str(dataset.crs),
                    dataset.width,
                    dataset.height,
                    tuple(dataset.transform),
                    tuple(dataset.bounds),
                    dataset.dtypes,
                )
        except Exception as exc:  # noqa: BLE001 - preserve driver-specific failure details
            reasons.append(f"{path} is unreadable or has invalid grid metadata: {exc}")

    raster_metadata = list(metadata.items())
    if raster_metadata:
        reference_name, reference = raster_metadata[0]
        for filename, candidate in raster_metadata[1:]:
            if candidate[:5] != reference[:5]:
                reasons.append(f"{filename} grid does not match {reference_name}")

    if isinstance(summary, dict):
        analysis_grid = summary.get("analysis_grid")
        expected_grid = {
            "crs": "EPSG:32633",
            "resolution_m": 20.0,
            "bounds": list(APPROVED_BOUNDS),
            "width": APPROVED_WIDTH,
            "height": APPROVED_HEIGHT,
        }
        if isinstance(analysis_grid, dict):
            for key, expected in expected_grid.items():
                actual = analysis_grid.get(key)
                if key == "bounds" and isinstance(actual, list):
                    try:
                        matches = bool(np.allclose(actual, expected, atol=1e-6))
                    except (TypeError, ValueError):
                        matches = False
                else:
                    matches = actual == expected
                if not matches:
                    reasons.append(
                        f"summary analysis_grid.{key} is {actual!r}, expected {expected!r}"
                    )

    return ValidationResult("INVALID" if reasons else "COMPLETE", tuple(reasons))


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_status(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(report, file, indent=2, sort_keys=True)
            file.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _year_record(
    year: int,
    status: str,
    before: ValidationResult,
    *,
    after: ValidationResult | None = None,
    exit_code: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "year": year,
        "status": status,
        "validation": {"before": before.as_dict()},
        "child_process": {"exit_code": exit_code},
    }
    if after is not None:
        record["validation"]["after"] = after.as_dict()
    if error is not None:
        record["error"] = error
    return record


def _command(
    config_path: Path,
    inventory_path: Path,
    output_root: Path,
    temp_root: Path,
    year: int,
    keep_temp_on_error: bool,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        ANNUAL_MODULE,
        "--year",
        str(year),
        "--config",
        str(config_path),
        "--inventory",
        str(inventory_path),
        "--output-root",
        str(output_root),
        "--temp-root",
        str(temp_root),
    ]
    if keep_temp_on_error:
        command.append("--keep-temp-on-error")
    return command


def run_batch(
    config_path: Path,
    inventory_path: Path,
    output_root: Path,
    temp_root: Path,
    years: Sequence[int],
    *,
    dry_run: bool = False,
    keep_temp_on_error: bool = False,
    runner: Any | None = None,
) -> dict[str, Any]:
    """Run requested years sequentially and return the generated report.

    ``runner`` is injectable for deterministic offline tests; production calls
    use ``subprocess.run`` and therefore launch no concurrent work.
    """
    config = load_config(config_path)
    process_runner = subprocess.run if runner is None else runner
    requested_years = normalize_years(years, config)
    annual_root = Path(output_root)
    start_timestamp = _timestamp()
    validations = {
        year: classify_annual_output(annual_root / str(year), year, config)
        for year in requested_years
    }

    for year in requested_years:
        validation = validations[year]
        if dry_run:
            action = {"COMPLETE": "would skip", "MISSING": "would build"}.get(
                validation.state, "cannot build"
            )
            print(f"{year}: {validation.state}; {action}")
            for reason in validation.reasons:
                if validation.state == "INVALID":
                    print(f"  - {reason}")
        else:
            print(f"{year}: {validation.state}")
            if validation.state == "INVALID":
                for reason in validation.reasons:
                    print(f"  - {reason}")

    if dry_run:
        return {
            "requested_years": list(requested_years),
            "years": [
                _year_record(
                    year,
                    "skipped_complete"
                    if validations[year].state == "COMPLETE"
                    else "not_attempted",
                    validations[year],
                )
                for year in requested_years
            ],
            "overall_status": "failure"
            if any(result.state == "INVALID" for result in validations.values())
            else "success",
            "dry_run": True,
            "started_at": start_timestamp,
            "finished_at": _timestamp(),
        }

    records: list[dict[str, Any]] = []
    overall_status = "success"
    for index, year in enumerate(requested_years):
        before = validations[year]
        if before.state == "COMPLETE":
            print(f"{year}: skipping COMPLETE annual outputs")
            records.append(_year_record(year, "skipped_complete", before, after=before))
            continue
        if before.state == "INVALID":
            records.append(
                _year_record(
                    year,
                    "failed",
                    before,
                    after=before,
                    error=(
                        "invalid existing annual outputs; rebuild explicitly "
                        "after investigation"
                    ),
                )
            )
            for later_year in requested_years[index + 1 :]:
                records.append(_year_record(later_year, "not_attempted", validations[later_year]))
            overall_status = "failure"
            break

        print(f"{year}: launching one isolated annual child process", flush=True)
        try:
            completed = process_runner(
                _command(
                    config_path,
                    inventory_path,
                    output_root,
                    temp_root,
                    year,
                    keep_temp_on_error,
                ),
                check=False,
            )
        except OSError as exc:
            after = classify_annual_output(annual_root / str(year), year, config)
            records.append(
                _year_record(
                    year,
                    "failed",
                    before,
                    after=after,
                    error=f"could not launch annual child process: {exc}",
                )
            )
            for later_year in requested_years[index + 1 :]:
                records.append(_year_record(later_year, "not_attempted", validations[later_year]))
            overall_status = "failure"
            break

        exit_code = int(completed.returncode)
        after = classify_annual_output(annual_root / str(year), year, config)
        if exit_code != 0:
            records.append(
                _year_record(
                    year,
                    "failed",
                    before,
                    after=after,
                    exit_code=exit_code,
                    error=f"annual child process exited with code {exit_code}",
                )
            )
            for later_year in requested_years[index + 1 :]:
                records.append(_year_record(later_year, "not_attempted", validations[later_year]))
            overall_status = "failure"
            break
        if after.state != "COMPLETE":
            error = "annual child exited successfully but final outputs are not COMPLETE"
            records.append(
                _year_record(
                    year,
                    "failed",
                    before,
                    after=after,
                    exit_code=exit_code,
                    error=error,
                )
            )
            for later_year in requested_years[index + 1 :]:
                records.append(_year_record(later_year, "not_attempted", validations[later_year]))
            overall_status = "failure"
            break
        print(f"{year}: built successfully and validated COMPLETE", flush=True)
        records.append(
            _year_record(year, "built_successfully", before, after=after, exit_code=exit_code)
        )

    report = {
        "requested_years": list(requested_years),
        "years": records,
        "overall_status": overall_status,
        "dry_run": False,
        "started_at": start_timestamp,
        "finished_at": _timestamp(),
    }
    _write_status(annual_root / "build-status.json", report)
    print(f"Annual batch {overall_status}; status written to {annual_root / 'build-status.json'}")
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        required=True,
        help="one or more explicit configured years; duplicates are sorted and removed",
    )
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--inventory", type=Path, default=Path("data/inventory/stac-items.json"))
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/annual"))
    parser.add_argument("--temp-root", type=Path, default=Path("data/.tmp/annual"))
    parser.add_argument(
        "--dry-run", action="store_true", help="validate and report without building"
    )
    parser.add_argument(
        "--keep-temp-on-error",
        action="store_true",
        help="pass through to the single-year child for diagnostic retention",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_batch(
            args.config,
            args.inventory,
            args.output_root,
            args.temp_root,
            args.years,
            dry_run=args.dry_run,
            keep_temp_on_error=args.keep_temp_on_error,
        )
    except ValueError as exc:
        print(f"Annual batch configuration error: {exc}", file=sys.stderr)
        return 2
    return 0 if report["overall_status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
