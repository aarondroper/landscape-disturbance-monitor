import copy
import json
from pathlib import Path

import pytest

import landscape_monitor.build_web_data as web

ROOT = Path(__file__).parents[1]


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a tiny complete source package for web-data unit tests."""
    repo = tmp_path / "repo"
    config_path = repo / "config" / "project.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes((ROOT / "config" / "project.toml").read_bytes())
    monkeypatch.setattr(web, "EXPECTED_DISTURBANCE_COUNT", 1)

    identifier = "disturbance-001"
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [[[
            [15.123456, 61.123456],
            [15.133456, 61.123456],
            [15.133456, 61.133456],
            [15.123456, 61.133456],
            [15.123456, 61.123456],
        ]]],
    }
    feature = {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "disturbance_id": identifier,
            "area_ha": 1.5,
            "touches_aoi_boundary": False,
            "nbr_2017_median": 0.7,
            "nbr_2018_median": 0.2,
            "dnbr_median": 0.5,
        },
    }
    years = web.ANNUAL_YEARS
    series = [
        {
            "year": year,
            "nbr_median": 0.2 + (year - 2017) * 0.01,
            "recovery_median": 0.1 + (year - 2017) * 0.05,
            "recovery_p10": 0.05,
            "recovery_p90": 0.15,
            "nbr_valid_fraction": 1.0,
            "nbr_coverage_status": "GOOD",
            "recovery_reporting_recommended": True,
            "recovery_valid_fraction": 1.0,
            "ndvi_median": 0.4,
            "ndvi_valid_fraction": 1.0,
        }
        for year in years
    ]
    completeness = [
        {"disturbance_id": identifier, "year": year, "category": "GOOD", "valid_fraction": 1.0}
        for year in years
    ]
    landscape = [
        {
            "year": year,
            "nbr_median": 0.2,
            "recovery_median": 0.5,
            "recovery_p10": 0.4,
            "recovery_p90": 0.6,
            "valid_nbr_fraction": 1.0,
            "fraction_ge_050": 0.5,
            "fraction_ge_080": 0.2,
            "fraction_ge_100": 0.1,
            "fraction_lt_000": 0.0,
            "fraction_gt_100": 0.1,
            "ndvi_median": 0.4,
            "ndvi_valid_fraction": 1.0,
        }
        for year in years
    ]
    by_year = [
        {
            "year": year,
            "GOOD": 1,
            "USABLE_WITH_COVERAGE_FLAG": 0,
            "POOR": 0,
            "zero_valid_object_count": 0,
        }
        for year in years
    ]
    derived = repo / "data" / "derived"
    sources = {
        "disturbance/disturbances.geojson": {"type": "FeatureCollection", "features": [feature]},
        "disturbance/disturbance-summary.json": {
            "objects": [{"disturbance_id": identifier, "area_ha": 1.5}],
            "components": {"retained_area_ha": 1.5},
        },
        "recovery/disturbance-timeseries.json": {
            "years": years,
            "disturbances": [{"disturbance_id": identifier, "area_ha": 1.5, "series": series}],
        },
        "recovery/recovery-summary.json": {
            "years": years,
            "landscape_annual_series": landscape,
            "coverage_status_summary": {"by_year": by_year},
        },
        "diagnostics/annual-completeness/annual-nbr-completeness.json": {
            "years": years,
            "disturbances": completeness,
            "landscape": [
                {"year": year, "retained_disturbance_nbr_valid_fraction": 1.0}
                for year in years
            ],
        },
        "web-delivery/imagery-manifest.json": {"benchmark_years": web.BENCHMARK_YEARS},
    }
    for relative, payload in sources.items():
        path = derived / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return repo


def test_source_context_reconciles_fixture_ids_and_annual_records(synthetic_repo: Path):
    context = web._source_context(web._source_paths(synthetic_repo))
    assert len(context["geo"]["features"]) == 1
    assert list(context["ts_by_id"]) == sorted(context["ts_by_id"])
    assert all(len(item["series"]) == 10 for item in context["ts_by_id"].values())
    assert all(
        [row["year"] for row in item["series"]] == web.ANNUAL_YEARS
        for item in context["ts_by_id"].values()
    )


def test_five_decimal_coordinate_rounding_passes_without_simplification(synthetic_repo: Path):
    context = web._source_context(web._source_paths(synthetic_repo))
    decimals, features, qa = web.choose_coordinate_precision(context)
    assert decimals == 5
    assert qa["passes"] is True
    assert qa["invalid_features"] == []
    assert qa["new_overlaps"] == []
    assert abs(qa["total_area_difference_percent"]) < web.TOTAL_AREA_MAX_PERCENT
    assert qa["maximum_absolute_feature_area_difference_percent"] < web.FEATURE_AREA_MAX_PERCENT
    assert qa["median_absolute_feature_area_difference_percent"] < web.FEATURE_AREA_MAX_PERCENT
    source = _load(web._source_paths(synthetic_repo)["disturbance_geojson"])
    source_coordinates = source["features"][0]["geometry"]["coordinates"]
    rounded_coordinates = features[0]["geometry"]["coordinates"]
    assert rounded_coordinates != source_coordinates
    assert len(rounded_coordinates) == len(source_coordinates)
    assert all(
        round(coordinate, 5) == coordinate
        for polygon in rounded_coordinates
        for ring in polygon
        for coordinate_pair in ring
        for coordinate in coordinate_pair
    )


def test_coordinate_fallback_retries_once_at_six_decimals(synthetic_repo: Path):
    context = web._source_context(web._source_paths(synthetic_repo))
    calls = []

    def qa_function(source, rounded):
        calls.append(rounded)
        return {
            "passes": len(calls) == 2,
            "total_area_difference_percent": 0.0,
            "maximum_absolute_feature_area_difference_percent": 0.0,
            "invalid_features": [],
            "new_overlaps": [],
        }

    decimals, _, qa = web.choose_coordinate_precision(context, qa_function=qa_function)
    assert decimals == 6
    assert qa["passes"] is True
    assert len(calls) == 2


def test_both_coordinate_precisions_fail_loudly(synthetic_repo: Path):
    context = web._source_context(web._source_paths(synthetic_repo))

    def qa_function(source, rounded):
        return {
            "passes": False,
            "total_area_difference_percent": 0.2,
            "maximum_absolute_feature_area_difference_percent": 0.6,
            "invalid_features": ["disturbance-001"],
            "new_overlaps": [],
        }

    with pytest.raises(web.WebDataBuildError, match="both permitted precisions"):
        web.choose_coordinate_precision(context, qa_function=qa_function)


def test_build_outputs_are_compact_reconciled_and_deterministic(synthetic_repo: Path):
    output_dir = synthetic_repo / "data" / "derived" / "web-delivery" / "data"
    first = web.build(synthetic_repo, output_dir)
    first_bytes = {name: (output_dir / name).read_bytes() for name in web.OUTPUT_FILENAMES}
    second = web.build(synthetic_repo, output_dir)
    second_bytes = {name: (output_dir / name).read_bytes() for name in web.OUTPUT_FILENAMES}
    assert first["coordinate_decimals"] == second["coordinate_decimals"] == 5
    assert first_bytes == second_bytes
    assert first["outputs"] == second["outputs"]
    assert all(b"\n" not in data for data in first_bytes.values())

    geo = json.loads(first_bytes["disturbances.geojson"])
    timeseries = json.loads(first_bytes["disturbance-timeseries.json"])
    summary = json.loads(first_bytes["summary.json"])
    manifest = json.loads(first_bytes["data-manifest.json"])
    geo_ids = [feature["properties"]["disturbance_id"] for feature in geo["features"]]
    assert geo_ids == sorted(geo_ids)
    assert geo_ids == list(timeseries["disturbances"])
    assert len(geo["features"]) == len(timeseries["disturbances"]) == 1
    assert list(timeseries["disturbances"]) == sorted(timeseries["disturbances"])
    assert all(len(item["series"]) == 10 for item in timeseries["disturbances"].values())
    assert summary["project"]["benchmark_imagery_years"] == web.BENCHMARK_YEARS
    assert summary["project"]["disturbance_object_count"] == 1
    assert manifest["geojson"]["geometry_simplification"] is False
    assert manifest["geojson"]["coordinate_decimal_places"] == 5
    assert all("/home/" not in json.dumps(manifest) for _ in [0])
    assert all(
        set(feature["properties"])
        == {
            "disturbance_id",
            "area_ha",
            "touches_aoi_boundary",
            "nbr_2017_median",
            "nbr_2018_median",
            "dnbr_median",
            "recovery_2026_median",
            "recovery_2026_valid_fraction",
            "recovery_2026_coverage_status",
            "recovery_2026_reporting_recommended",
        }
        for feature in geo["features"]
    )
    assert all(
        "ndvi_recovery" not in row
        for item in timeseries["disturbances"].values()
        for row in item["series"]
    )
    for feature in geo["features"]:
        identifier = feature["properties"]["disturbance_id"]
        row = next(
            item
            for item in timeseries["disturbances"][identifier]["series"]
            if item["year"] == 2026
        )
        assert feature["properties"]["recovery_2026_median"] == row["recovery_median"]
        assert (
            feature["properties"]["recovery_2026_valid_fraction"]
            == row["nbr_valid_fraction"]
        )
        assert feature["properties"]["recovery_2026_coverage_status"] == row["coverage_status"]
        assert (
            feature["properties"]["recovery_2026_reporting_recommended"]
            == row["reporting_recommended"]
        )
    assert manifest["files"][0]["sha256"] == web._sha256_file(
        output_dir / "disturbances.geojson"
    )


def test_payload_precision_nulls_and_finite_serialization():
    assert web._round_number(None, 4, "test") is None
    assert web._round_number(0.123456, 4, "test") == 0.1235
    assert web._compact_json_bytes({"value": None, "number": 0.1235}) == (
        b'{"value":null,"number":0.1235}'
    )
    with pytest.raises(web.WebDataBuildError):
        web._round_number(float("nan"), 4, "test")
    with pytest.raises(ValueError):
        json.dumps({"value": float("nan")}, allow_nan=False)


def test_output_path_cannot_target_analytical_data(tmp_path: Path):
    with pytest.raises(web.WebDataBuildError, match="analytical"):
        web._validate_output_dir(ROOT / "data" / "derived" / "disturbance", ROOT)
    with pytest.raises(web.WebDataBuildError, match="must be data"):
        web._validate_output_dir(tmp_path / "wrong", ROOT)


def test_build_does_not_change_source_hashes(synthetic_repo: Path):
    paths = web._source_paths(synthetic_repo)
    before = web.source_hashes(paths)
    web.build(synthetic_repo, synthetic_repo / "data" / "derived" / "web-delivery" / "data")
    assert before == web.source_hashes(paths)


def test_source_copy_is_not_simplified_or_repaired(synthetic_repo: Path):
    source = _load(web._source_paths(synthetic_repo)["disturbance_geojson"])
    copied = copy.deepcopy(source["features"][0]["geometry"])
    rounded = web._rounded_geometry(source["features"][0], 5)
    assert copied["type"] == rounded["type"] == "MultiPolygon"
    assert len(copied["coordinates"]) == len(rounded["coordinates"])
