import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import landscape_monitor.build_annual_batch as batch
from landscape_monitor.config import load_config

CONFIG = Path(__file__).parents[1] / "config" / "project.toml"
PROJECT_CONFIG = load_config(CONFIG)
TRANSFORM = from_origin(506260.0, 6883240.0, 20.0, 20.0)


def _write_raster(path: Path, dtype: str = "float32", transform=TRANSFORM) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nodata = 65535 if dtype == "uint16" else -9999.0
    value = 1 if dtype == "uint16" else 0.5
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=batch.APPROVED_WIDTH,
        height=batch.APPROVED_HEIGHT,
        count=1,
        dtype=dtype,
        crs="EPSG:32633",
        transform=transform,
        nodata=nodata,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="deflate",
    ) as dataset:
        dataset.write(np.full((batch.APPROVED_HEIGHT, batch.APPROVED_WIDTH), value, dtype=dtype), 1)


def _valid_summary(year: int) -> dict:
    return {
        "processing_version": "milestone-4A memory-bounded annual composite v1",
        "year": year,
        "requested_interval": {"start": f"{year}-08-01", "end": f"{year}-08-31"},
        "stac_item_count": 1,
        "grouped_acquisition_count": 1,
        "usable_acquisition_count": 1,
        "analysis_grid": {
            "crs": "EPSG:32633",
            "resolution_m": 20.0,
            "bounds": list(batch.APPROVED_BOUNDS),
            "width": batch.APPROVED_WIDTH,
            "height": batch.APPROVED_HEIGHT,
        },
        "valid_coverage": {"nbr_percent": 100.0, "ndvi_percent": 100.0},
        "nbr_distribution": {"count": 1, "median": 0.5, "min": 0.5, "max": 0.5},
        "ndvi_distribution": {"count": 1, "median": 0.5, "min": 0.5, "max": 0.5},
        "processing": {
            "temporal_statistic": "exact per-pixel median across valid acquisition dates"
        },
        "memory_telemetry": {"peak_max_rss_mib": 1.0},
        "temporary_storage": {"peak_bytes": 1},
        "reduction": {"block_count": 1},
        "outputs": {
            "files": {
                "nbr": "nbr.tif",
                "ndvi": "ndvi.tif",
                "valid_count": "valid_count.tif",
                "summary": "annual-summary.json",
            }
        },
    }


def _write_complete_year(output_root: Path, year: int) -> Path:
    annual_dir = output_root / str(year)
    _write_raster(annual_dir / "nbr.tif")
    _write_raster(annual_dir / "ndvi.tif")
    _write_raster(annual_dir / "valid_count.tif", dtype="uint16")
    (annual_dir / "annual-summary.json").write_text(
        json.dumps(_valid_summary(year)), encoding="utf-8"
    )
    return annual_dir


def _fake_runner_factory(output_root: Path, calls: list[int], failures=None):
    failures = failures or {}

    def runner(command, check=False):
        assert check is False
        year = int(command[command.index("--year") + 1])
        calls.append(year)
        if year not in failures:
            _write_complete_year(output_root, year)
        return SimpleNamespace(returncode=failures.get(year, 0))

    return runner


def test_requested_years_are_required_and_all_mode_is_unavailable():
    with pytest.raises(SystemExit):
        batch.parse_args([])
    with pytest.raises(SystemExit):
        batch.parse_args(["--all"])
    with pytest.raises(SystemExit):
        batch.parse_args(["--years"])
    with pytest.raises(SystemExit):
        batch.parse_args(["--years", "twenty-nineteen"])


def test_unsupported_years_fail_and_duplicates_are_sorted():
    with pytest.raises(ValueError, match="unsupported year"):
        batch.normalize_years([2019, 1900], PROJECT_CONFIG)
    assert batch.normalize_years([2020, 2019, 2020], PROJECT_CONFIG) == (2019, 2020)


def test_complete_annual_directory_is_validated(tmp_path: Path):
    annual_dir = _write_complete_year(tmp_path / "annual", 2019)
    result = batch.classify_annual_output(annual_dir, 2019, PROJECT_CONFIG)
    assert result.state == "COMPLETE"
    assert result.reasons == ()


def test_missing_directory_is_missing_but_partial_directory_is_invalid(tmp_path: Path):
    root = tmp_path / "annual"
    assert batch.classify_annual_output(root / "2019", 2019, PROJECT_CONFIG).state == "MISSING"
    (root / "2019").mkdir(parents=True)
    assert batch.classify_annual_output(root / "2019", 2019, PROJECT_CONFIG).state == "MISSING"
    (root / "2019" / "partial.tif").write_bytes(b"partial")
    result = batch.classify_annual_output(root / "2019", 2019, PROJECT_CONFIG)
    assert result.state == "INVALID"
    assert "missing required output file(s)" in result.reasons[0]


def test_malformed_summary_and_wrong_year_are_invalid(tmp_path: Path):
    annual_dir = _write_complete_year(tmp_path / "annual", 2019)
    summary_path = annual_dir / "annual-summary.json"
    summary_path.write_text("{not-json", encoding="utf-8")
    assert batch.classify_annual_output(annual_dir, 2019, PROJECT_CONFIG).state == "INVALID"

    summary_path.write_text(json.dumps(_valid_summary(2020)), encoding="utf-8")
    result = batch.classify_annual_output(annual_dir, 2019, PROJECT_CONFIG)
    assert result.state == "INVALID"
    assert "summary year" in " ".join(result.reasons)

    summary_path.write_text(json.dumps({"outputs": []}), encoding="utf-8")
    result = batch.classify_annual_output(annual_dir, 2019, PROJECT_CONFIG)
    assert result.state == "INVALID"
    assert "summary outputs must be an object" in result.reasons


def test_mismatched_grid_and_unreadable_raster_are_invalid(tmp_path: Path):
    annual_dir = _write_complete_year(tmp_path / "annual", 2019)
    _write_raster(annual_dir / "ndvi.tif", transform=from_origin(506280.0, 6883240.0, 20, 20))
    result = batch.classify_annual_output(annual_dir, 2019, PROJECT_CONFIG)
    assert result.state == "INVALID"
    assert "transform" in " ".join(result.reasons)

    (annual_dir / "nbr.tif").write_bytes(b"not a GeoTIFF")
    result = batch.classify_annual_output(annual_dir, 2019, PROJECT_CONFIG)
    assert result.state == "INVALID"
    assert "unreadable" in " ".join(result.reasons)


def test_complete_year_is_skipped_and_missing_year_launches_once(tmp_path: Path):
    output_root = tmp_path / "annual"
    _write_complete_year(output_root, 2019)
    calls: list[int] = []
    report = batch.run_batch(
        CONFIG,
        tmp_path / "inventory.json",
        output_root,
        tmp_path / "tmp",
        [2019, 2020],
        runner=_fake_runner_factory(output_root, calls),
    )
    assert calls == [2020]
    assert [record["status"] for record in report["years"]] == [
        "skipped_complete",
        "built_successfully",
    ]


def test_years_are_processed_sequentially_without_concurrency(tmp_path: Path):
    calls: list[int] = []
    active = 0
    maximum_active = 0
    output_root = tmp_path / "annual"

    def runner(command, check=False):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        year = int(command[command.index("--year") + 1])
        calls.append(year)
        _write_complete_year(output_root, year)
        active -= 1
        return SimpleNamespace(returncode=0)

    batch.run_batch(
        CONFIG,
        tmp_path / "inventory.json",
        output_root,
        tmp_path / "tmp",
        [2020, 2019],
        runner=runner,
    )
    assert calls == [2019, 2020]
    assert maximum_active == 1


def test_child_failure_preserves_previous_year_and_marks_later_not_attempted(tmp_path: Path):
    output_root = tmp_path / "annual"
    calls: list[int] = []
    report = batch.run_batch(
        CONFIG,
        tmp_path / "inventory.json",
        output_root,
        tmp_path / "tmp",
        [2019, 2020, 2021],
        runner=_fake_runner_factory(output_root, calls, failures={2020: 7}),
    )
    assert calls == [2019, 2020]
    assert (output_root / "2019" / "annual-summary.json").exists()
    assert [record["status"] for record in report["years"]] == [
        "built_successfully",
        "failed",
        "not_attempted",
    ]
    assert report["years"][1]["child_process"]["exit_code"] == 7
    assert report["overall_status"] == "failure"


def test_invalid_existing_output_stops_before_launching(tmp_path: Path):
    output_root = tmp_path / "annual"
    _write_complete_year(output_root, 2019)
    (output_root / "2020").mkdir(parents=True)
    (output_root / "2020" / "partial.tif").write_bytes(b"partial")
    calls: list[int] = []
    report = batch.run_batch(
        CONFIG,
        tmp_path / "inventory.json",
        output_root,
        tmp_path / "tmp",
        [2019, 2020, 2021],
        runner=_fake_runner_factory(output_root, calls),
    )
    assert calls == []
    assert [record["status"] for record in report["years"]] == [
        "skipped_complete",
        "failed",
        "not_attempted",
    ]


def test_year_before_later_invalid_output_is_processed_first(tmp_path: Path):
    output_root = tmp_path / "annual"
    (output_root / "2021").mkdir(parents=True)
    (output_root / "2021" / "partial.tif").write_bytes(b"partial")
    calls: list[int] = []
    report = batch.run_batch(
        CONFIG,
        tmp_path / "inventory.json",
        output_root,
        tmp_path / "tmp",
        [2020, 2021],
        runner=_fake_runner_factory(output_root, calls),
    )
    assert calls == [2020]
    assert [record["status"] for record in report["years"]] == [
        "built_successfully",
        "failed",
    ]


def test_child_launch_failure_is_recorded_and_stops_later_years(tmp_path: Path):
    output_root = tmp_path / "annual"

    def runner(command, check=False):
        raise OSError("child executable unavailable")

    report = batch.run_batch(
        CONFIG,
        tmp_path / "inventory.json",
        output_root,
        tmp_path / "tmp",
        [2020, 2021],
        runner=runner,
    )
    assert [record["status"] for record in report["years"]] == [
        "failed",
        "not_attempted",
    ]
    assert "could not launch" in report["years"][0]["error"]
    assert report["years"][0]["child_process"]["exit_code"] is None


def test_successful_child_with_incomplete_outputs_is_failed(tmp_path: Path):
    output_root = tmp_path / "annual"

    def runner(command, check=False):
        return SimpleNamespace(returncode=0)

    report = batch.run_batch(
        CONFIG,
        tmp_path / "inventory.json",
        output_root,
        tmp_path / "tmp",
        [2020, 2021],
        runner=runner,
    )
    assert [record["status"] for record in report["years"]] == [
        "failed",
        "not_attempted",
    ]
    assert "not COMPLETE" in report["years"][0]["error"]


def test_dry_run_launches_no_child_and_writes_no_status(tmp_path: Path):
    output_root = tmp_path / "annual"
    calls: list[int] = []
    report = batch.run_batch(
        CONFIG,
        tmp_path / "inventory.json",
        output_root,
        tmp_path / "tmp",
        [2019, 2020],
        dry_run=True,
        runner=_fake_runner_factory(output_root, calls),
    )
    assert calls == []
    assert not (output_root / "build-status.json").exists()
    assert report["dry_run"] is True
    assert report["requested_years"] == [2019, 2020]


def test_status_is_ordered_and_contains_validation_and_exit_code(tmp_path: Path):
    output_root = tmp_path / "annual"
    _write_complete_year(output_root, 2019)
    calls: list[int] = []
    batch.run_batch(
        CONFIG,
        tmp_path / "inventory.json",
        output_root,
        tmp_path / "tmp",
        [2020, 2019, 2020],
        runner=_fake_runner_factory(output_root, calls),
    )
    report = json.loads((output_root / "build-status.json").read_text(encoding="utf-8"))
    assert report["requested_years"] == [2019, 2020]
    assert [record["year"] for record in report["years"]] == [2019, 2020]
    assert report["years"][0]["validation"]["before"]["state"] == "COMPLETE"
    assert report["years"][1]["child_process"]["exit_code"] == 0
    assert report["overall_status"] == "success"
    assert set(report) == {
        "dry_run",
        "finished_at",
        "overall_status",
        "requested_years",
        "started_at",
        "years",
    }
