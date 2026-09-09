from landscape_monitor.stac_probe import summarise_year


def test_summarise_year_is_deterministic_for_mocked_items():
    items = [
        {
            "id": "b",
            "datetime": "2020-08-20T10:00:00Z",
            "eo:cloud_cover": 40,
            "mgrs": {"s2:mgrs_tile": "33VWE"},
            "mgrs_tile": "33VWE",
            "relevant_assets": {
                "blue": [{"key": "blue"}],
                "green": [{"key": "green"}],
                "red": [{"key": "red"}],
                "nir": [{"key": "nir"}],
                "swir2": [{"key": "swir22"}],
                "scl": [{"key": "scl"}],
            },
        },
        {
            "id": "a",
            "datetime": "2020-08-02T10:00:00Z",
            "eo:cloud_cover": 10,
            "mgrs": {"s2:mgrs_tile": "33VWE"},
            "mgrs_tile": "33VWE",
            "relevant_assets": {
                "blue": [{"key": "blue"}],
                "green": [{"key": "green"}],
                "red": [{"key": "red"}],
                "nir": [{"key": "nir"}],
                "swir2": [{"key": "swir22"}],
                "scl": [{"key": "scl"}],
            },
        },
    ]

    summary = summarise_year(items, 2020)

    assert summary["candidate_observations"] == 2
    assert summary["date_range"] == {"min": "2020-08-02T10:00:00Z", "max": "2020-08-20T10:00:00Z"}
    assert summary["cloud_cover"] == {"min": 10.0, "median": 25.0, "max": 40.0}
    assert summary["intersecting_mgrs_tiles"] == ["33VWE"]
    assert summary["all_required_future_assets_available"] is True
    assert summary["items_with_all_required_assets"] == 2


def test_summarise_year_reports_missing_required_asset():
    summary = summarise_year(
        [{"id": "one", "datetime": None, "mgrs": {}, "relevant_assets": {"red": [{"key": "red"}]}}],
        2021,
    )

    assert summary["all_required_future_assets_available"] is False
    assert summary["required_assets_present"]["red"] is True
    assert summary["required_assets_present"]["nir"] is False
