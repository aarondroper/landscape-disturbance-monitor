import copy
import json
from pathlib import Path

import pytest

import landscape_monitor.build_web_data as web

ROOT = Path(__file__).parents[1]
SOURCE_GEOJSON = ROOT / "data" / "derived" / "disturbance" / "disturbances.geojson"

pytestmark = [
    pytest.mark.generated_data,
    pytest.mark.skipif(
        not SOURCE_GEOJSON.is_file(), reason="local generated disturbance package is absent"
    ),
]


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_generated_source_context_reconciles_80_ids_and_80_by_10_records():
    context = web._source_context(web._source_paths(ROOT))
    assert len(context["geo"]["features"]) == 80
    assert list(context["ts_by_id"]) == sorted(context["ts_by_id"])
    assert all(len(item["series"]) == 10 for item in context["ts_by_id"].values())
    assert all(
        [row["year"] for row in item["series"]] == web.ANNUAL_YEARS
        for item in context["ts_by_id"].values()
    )


def test_generated_five_decimal_coordinate_rounding_passes_without_simplification():
    context = web._source_context(web._source_paths(ROOT))
    decimals, features, qa = web.choose_coordinate_precision(context)
    assert decimals == 5
    assert qa["passes"] is True
    assert qa["invalid_features"] == []
    assert qa["new_overlaps"] == []
    assert qa["total_area_difference_percent"] == pytest.approx(-0.0028011159)
    assert qa["maximum_absolute_feature_area_difference_percent"] == pytest.approx(0.2133822318)
    assert qa["median_absolute_feature_area_difference_percent"] == pytest.approx(0.0257456137)
    source = _load(SOURCE_GEOJSON)
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


def test_generated_coordinate_fallback_retries_once_at_six_decimals():
    context = web._source_context(web._source_paths(ROOT))
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


def test_generated_coordinate_precisions_fail_loudly_when_both_qa_attempts_fail():
    context = web._source_context(web._source_paths(ROOT))

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


def test_generated_build_outputs_are_compact_reconciled_and_deterministic(tmp_path: Path):
    output_dir = tmp_path / "web-delivery" / "data"
    first = web.build(ROOT, output_dir)
    first_bytes = {name: (output_dir / name).read_bytes() for name in web.OUTPUT_FILENAMES}
    second = web.build(ROOT, output_dir)
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
    assert len(geo["features"]) == len(timeseries["disturbances"]) == 80
    assert list(timeseries["disturbances"]) == sorted(timeseries["disturbances"])
    assert all(len(item["series"]) == 10 for item in timeseries["disturbances"].values())
    assert summary["project"]["benchmark_imagery_years"] == web.BENCHMARK_YEARS
    assert manifest["geojson"]["geometry_simplification"] is False
    assert manifest["geojson"]["coordinate_decimal_places"] == 5
    assert "/home/" not in json.dumps(manifest)
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
        assert feature["properties"]["recovery_2026_valid_fraction"] == row["nbr_valid_fraction"]
        assert feature["properties"]["recovery_2026_coverage_status"] == row["coverage_status"]
        assert (
            feature["properties"]["recovery_2026_reporting_recommended"]
            == row["reporting_recommended"]
        )
    assert manifest["files"][0]["sha256"] == web._sha256_file(
        output_dir / "disturbances.geojson"
    )


def test_generated_build_does_not_change_source_hashes():
    paths = web._source_paths(ROOT)
    before = web.source_hashes(paths)
    web.build(ROOT, ROOT / "data" / "derived" / "web-delivery" / "data")
    assert before == web.source_hashes(paths)


def test_generated_source_copy_is_not_simplified_or_repaired():
    source = _load(SOURCE_GEOJSON)
    copied = copy.deepcopy(source["features"][0]["geometry"])
    rounded = web._rounded_geometry(source["features"][0], 5)
    assert copied["type"] == rounded["type"] == "MultiPolygon"
    assert len(copied["coordinates"]) == len(rounded["coordinates"])
