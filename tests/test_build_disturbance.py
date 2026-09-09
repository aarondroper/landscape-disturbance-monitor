import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from landscape_monitor.build_disturbance import (
    BASELINE_SENSITIVITY,
    DNBR_SENSITIVITY,
    PATCH_SENSITIVITY,
    candidate_mask,
    component_statistics,
    deterministic_relabel,
    filter_components,
    geometry_coordinate_count,
    label_connected_components,
    load_prototype_arrays,
    min_pixels_for_area,
    polygonize_components,
    sensitivity_analysis,
    to_wgs84_geometry,
    touches_aoi_boundary,
)
from landscape_monitor.config import load_config

CONFIG = Path(__file__).parents[1] / "config" / "project.toml"


def test_candidate_mask_is_strict_for_baseline_and_inclusive_for_dnbr():
    pre = np.array([[0.29, 0.30, 0.31, np.nan]], dtype=np.float32)
    change = np.array([[0.31, 0.30, 0.299, 0.30]], dtype=np.float32)
    result = candidate_mask(pre, change, 0.30, 0.30)
    assert result.tolist() == [[False, False, False, False]]
    result = candidate_mask(pre, change, 0.30, 0.299)
    assert result.tolist() == [[False, False, True, False]]


def test_candidate_mask_excludes_nodata_even_if_thresholds_are_met():
    pre = np.array([[0.8, np.nan], [0.8, 0.8]], dtype=np.float32)
    change = np.array([[0.5, 0.5], [np.nan, 0.5]], dtype=np.float32)
    result = candidate_mask(pre, change, 0.3, 0.3)
    assert result.tolist() == [[True, False], [False, True]]


def test_8_neighbour_connectivity_joins_diagonal_pixels_only():
    mask = np.array([[True, False], [False, True]])
    labels_8, count_8 = label_connected_components(mask, 8)
    labels_4, count_4 = label_connected_components(mask, 4)
    assert count_8 == 1 and labels_8[0, 0] == labels_8[1, 1]
    assert count_4 == 2 and labels_4[0, 0] != labels_4[1, 1]


def test_minimum_area_filter_and_hectare_conversion():
    labels = np.array([[1, 1, 2], [0, 1, 2]], dtype=np.int32)
    filtered, before, retained = filter_components(labels, min_pixels_for_area(0.12))
    assert before == 2 and retained == 1
    assert filtered.tolist() == [[1, 1, 0], [0, 1, 0]]
    assert min_pixels_for_area(5.0) == 125


def test_object_statistics_use_labelled_pixels_and_id_order_is_deterministic():
    labels = np.array([[1, 1, 0], [0, 2, 2]], dtype=np.int32)
    pre = np.array([[0.5, 0.6, np.nan], [np.nan, 0.7, 0.8]])
    post = np.array([[0.2, 0.3, np.nan], [np.nan, 0.4, 0.5]])
    change = pre - post
    aoi = np.ones(labels.shape, dtype=bool)
    records = component_statistics(
        labels, pre, post, change, from_origin(0, 4, 1, 1), aoi, pixel_area_ha=0.04
    )
    stable_labels, stable_records = deterministic_relabel(labels, records)
    assert stable_labels.shape == labels.shape
    assert [record["disturbance_id"] for record in stable_records] == [
        "disturbance-001",
        "disturbance-002",
    ]
    assert stable_records[0]["pixel_count"] == 2
    assert stable_records[0]["area_ha"] == 0.08
    assert stable_records[0]["nbr_2017_mean"] in (0.55, 0.75)
    assert stable_records[0]["dnbr_max"] in (0.3, 0.30000000000000004)


def test_aoi_boundary_touch_detection():
    aoi = np.ones((5, 5), dtype=bool)
    center = np.zeros((5, 5), dtype=bool)
    center[2, 2] = True
    edge = np.zeros((5, 5), dtype=bool)
    edge[0, 2] = True
    assert touches_aoi_boundary(center, aoi) is False
    assert touches_aoi_boundary(edge, aoi) is True


def test_polygonization_preserves_component_identity_and_transforms_to_wgs84():
    labels = np.array([[1, 1, 0], [1, 0, 2], [0, 2, 2]], dtype=np.int32)
    transform = from_origin(500000.0, 6900000.0, 20.0, 20.0)
    geometries = polygonize_components(labels, transform)
    assert set(geometries) == {1, 2}
    geojson_geometry = to_wgs84_geometry(geometries[1], "EPSG:32633")
    assert geojson_geometry["type"] in {"Polygon", "MultiPolygon"}
    assert geometry_coordinate_count(geojson_geometry) > 0
    coordinates = geojson_geometry["coordinates"]
    while isinstance(coordinates[0][0], list):
        coordinates = coordinates[0]
    assert 14.0 < coordinates[0][0] < 16.0
    assert 61.0 < coordinates[0][1] < 63.0


def test_sensitivity_analysis_returns_requested_one_dimensional_comparisons():
    pre = np.full((4, 4), 0.5, dtype=np.float32)
    change = np.full((4, 4), 0.35, dtype=np.float32)
    valid = np.ones((4, 4), dtype=bool)
    results = sensitivity_analysis(
        pre,
        change,
        valid,
        from_origin(0, 4, 1, 1),
        valid,
        0.30,
        0.30,
        5.0,
        8,
        pixel_area_ha=1.0,
    )
    assert [item["dnbr_min"] for item in results["dnbr_threshold"]] == list(DNBR_SENSITIVITY)
    assert [item["baseline_nbr_min"] for item in results["baseline_nbr_threshold"]] == list(
        BASELINE_SENSITIVITY
    )
    assert [item["min_patch_ha"] for item in results["minimum_patch_ha"]] == list(PATCH_SENSITIVITY)
    assert results["dnbr_threshold"][1]["retained_area_ha"] == 16.0
    assert results["minimum_patch_ha"][3]["retained_component_count"] == 1


def test_mismatched_input_grid_fails_explicitly(tmp_path):
    config = load_config(CONFIG)
    profile = {
        "driver": "GTiff",
        "height": 2,
        "width": 2,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:32633",
        "transform": from_origin(0, 40, 20, 20),
        "nodata": -9999.0,
    }
    for filename in ("nbr_2017.tif", "nbr_2018.tif", "dnbr_2017_2018.tif"):
        with rasterio.open(tmp_path / filename, "w", **profile) as dataset:
            dataset.write(np.ones((2, 2), dtype=np.float32), 1)
    with pytest.raises(ValueError, match="dimensions"):
        load_prototype_arrays(tmp_path, config)


def test_config_json_is_serializable_for_test_discipline():
    assert json.dumps({"baseline_nbr_min": 0.3, "connectivity": 8})
