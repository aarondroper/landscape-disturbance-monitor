from pathlib import Path

import pytest

import landscape_monitor.build_web_rasters as web

ROOT = Path(__file__).parents[1]
GENERATED_MANIFEST = ROOT / "data" / "derived" / "web-delivery" / "raster-manifest.json"

pytestmark = [
    pytest.mark.generated_data,
    pytest.mark.skipif(
        not GENERATED_MANIFEST.is_file(), reason="local generated web-raster package is absent"
    ),
]


def test_generated_web_manifests_reconcile_without_network_or_mutation():
    paths = web._source_paths(ROOT)
    before = web.capture_input_hashes(paths)
    assert web._manifest_reconciliation(paths) == {
        "annual_years": list(range(2017, 2027)),
        "benchmark_imagery_years": [2017, 2018, 2020, 2023, 2026],
    }
    assert web.capture_input_hashes(paths) == before
