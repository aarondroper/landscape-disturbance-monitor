import json

from landscape_monitor.validate_web_delivery import inspect_delivery, report


def test_delivery_inventory_counts_files_and_manifest_references(tmp_path):
    (tmp_path / "imagery" / "2018").mkdir(parents=True)
    (tmp_path / "data").mkdir()
    (tmp_path / "imagery" / "2018" / "rgb.tif").write_bytes(b"cog")
    (tmp_path / "data" / "summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "imagery-manifest.json").write_text(
        json.dumps({"imagery": {"2018": {"path": "imagery/2018/rgb.tif"}}}), encoding="utf-8"
    )

    inventory = inspect_delivery(tmp_path)

    assert inventory.file_count == 3
    assert inventory.total_bytes == 60
    assert inventory.cog_count == 1
    assert inventory.json_geojson_count == 2
    assert inventory.missing_manifest_files == ()
    assert "Missing files referenced by manifests:\n  none" in report(inventory)


def test_delivery_inventory_reports_missing_manifest_paths(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "data-manifest.json").write_text(
        json.dumps({"files": [{"path": "data/missing.geojson"}]}), encoding="utf-8"
    )

    inventory = inspect_delivery(tmp_path)

    assert inventory.missing_manifest_files == ("data/missing.geojson",)
