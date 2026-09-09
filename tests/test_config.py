from pathlib import Path

from landscape_monitor.config import load_config

CONFIG = Path(__file__).parents[1] / "config" / "project.toml"


def test_config_loads_and_validates():
    config = load_config(CONFIG)

    assert config.study_area_id == "karbole-ljusdal-2018-wildfire"
    assert config.aoi.as_list() == [15.12, 61.86, 15.6, 62.08]
    assert config.analysis_years == tuple(range(2017, 2027))
    assert config.benchmark_years == (2017, 2018, 2020, 2023, 2026)
    assert config.baseline_nbr_min == 0.30
    assert config.dnbr_min == 0.30
    assert config.min_patch_ha == 5.0
    assert config.connectivity == 8


def test_annual_august_intervals_are_utc_and_cover_august():
    intervals = load_config(CONFIG).annual_august_intervals()

    assert intervals[2017] == ("2017-08-01T00:00:00Z", "2017-09-01T00:00:00Z")
    assert intervals[2026] == ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
