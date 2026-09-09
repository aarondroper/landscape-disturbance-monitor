"""Read-only Earth Search discovery and remote COG feasibility probe."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import rasterio
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.windows import Window

from .config import ProjectConfig, load_config

REQUIRED_BANDS = ("blue", "green", "red", "nir", "swir2", "scl")
_BAND_ALIASES = {
    "blue": {"blue", "b02", "b2"},
    "green": {"green", "b03", "b3"},
    "red": {"red", "b04", "b4"},
    "nir": {"nir", "b08", "b8"},
    "swir2": {"swir2", "swir22", "b12"},
    "scl": {"scl", "sceneclassification", "sceneclassificationmap"},
}


def _normalise(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _asset_band_match(key: str, asset_dict: dict[str, Any]) -> tuple[str | None, str]:
    """Match an asset using STAC metadata, retaining an audit-friendly reason."""
    key_normalised = _normalise(key)
    for required, aliases in _BAND_ALIASES.items():
        if key_normalised in aliases:
            return required, "asset key"

    # Visual/preview assets can advertise B02/B03/B04 as their component bands,
    # but they are RGB renderings rather than the individual reflectance COGs.
    if key_normalised in {"visual", "visualjp2", "preview", "thumbnail"}:
        return None, ""

    candidates: list[tuple[str, str]] = []
    for field in ("title", "description", "name"):
        if asset_dict.get(field):
            candidates.append((str(asset_dict[field]), f"asset {field}"))
    eo_bands = asset_dict.get("eo:bands", []) or []
    for band in eo_bands:
        if isinstance(band, dict):
            for field in ("name", "common_name"):
                if band.get(field):
                    candidates.append((str(band[field]), f"eo:bands.{field}"))

    for required, aliases in _BAND_ALIASES.items():
        for value, reason in candidates:
            if _normalise(value) in aliases:
                return required, reason
    joined = " ".join(_normalise(value) for value, _ in candidates)
    if "sceneclassification" in joined:
        return "scl", "asset metadata text"
    return None, ""


def _is_cog_likely(asset_dict: dict[str, Any]) -> bool:
    asset_type = str(asset_dict.get("type", "")).lower()
    href = str(asset_dict.get("href", "")).lower()
    return (
        "cloud-optimized" in asset_type
        or "cloud_optimized" in asset_type
        or ("image/tiff" in asset_type and href.endswith((".tif", ".tiff")))
    )


def _item_datetime(item: Any) -> str | None:
    value = getattr(item, "datetime", None)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value) if value else item.properties.get("datetime")


def _metadata_properties(properties: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    return {name: properties[name] for name in names if properties.get(name) is not None}


def _mgrs_tile(properties: dict[str, Any]) -> str | None:
    direct = properties.get("s2:mgrs_tile") or properties.get("mgrs:tile")
    if direct:
        return str(direct)
    components = (
        properties.get("mgrs:utm_zone"),
        properties.get("mgrs:latitude_band"),
        properties.get("mgrs:grid_square"),
    )
    return "".join(str(value) for value in components) if all(components) else None


def serialise_item(item: Any, year: int) -> dict[str, Any]:
    """Extract deterministic, small metadata from a pystac Item."""
    properties = dict(item.properties)
    asset_records: dict[str, dict[str, Any]] = {}
    relevant_assets: dict[str, list[str]] = defaultdict(list)
    relevant_asset_details: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for key in sorted(item.assets):
        asset_dict = item.assets[key].to_dict()
        required, match_reason = _asset_band_match(key, asset_dict)
        record = {
            "href": asset_dict.get("href"),
            "type": asset_dict.get("type"),
            "roles": asset_dict.get("roles", []),
            "title": asset_dict.get("title"),
            "cog_likely": _is_cog_likely(asset_dict),
        }
        # Keep the small amount of raster-extension metadata needed by later
        # processing stages in the checked-in inventory.  In particular, the
        # reflectance scale/offset must come from STAC rather than an implicit
        # Sentinel-2 processing-baseline assumption.
        for metadata_name in ("eo:bands", "gsd", "proj:shape", "proj:transform", "raster:bands"):
            if asset_dict.get(metadata_name) is not None:
                record[metadata_name] = asset_dict[metadata_name]
        asset_records[key] = {name: value for name, value in record.items() if value is not None}
        if required:
            relevant_assets[required].append(key)
            relevant_asset_details[required].append(
                {"key": key, "match_basis": match_reason, **asset_records[key]}
            )

    mgrs_properties = {
        key: value
        for key, value in properties.items()
        if "mgrs" in key.lower() or key in {"grid:code", "s2:granule_id"}
    }
    projection = _metadata_properties(properties, ("proj:epsg", "proj:code", "proj:wkt2"))
    return {
        "year": year,
        "id": item.id,
        "datetime": _item_datetime(item),
        "collection": item.collection_id,
        "eo:cloud_cover": properties.get("eo:cloud_cover"),
        "platform": properties.get("platform"),
        "mgrs": mgrs_properties,
        "mgrs_tile": _mgrs_tile(properties),
        "projection": projection,
        "asset_keys": sorted(asset_records),
        "relevant_assets": dict(relevant_asset_details),
    }


def _cloud_stats(items: list[dict[str, Any]]) -> dict[str, float] | None:
    values = sorted(
        float(item["eo:cloud_cover"]) for item in items if item.get("eo:cloud_cover") is not None
    )
    if not values:
        return None
    return {"min": values[0], "median": median(values), "max": values[-1]}


def summarise_year(items: list[dict[str, Any]], year: int) -> dict[str, Any]:
    relevant_keys: dict[str, set[str]] = {band: set() for band in REQUIRED_BANDS}
    cog_keys: dict[str, set[str]] = {band: set() for band in REQUIRED_BANDS}
    mgrs_tiles: set[str] = set()
    dates = sorted(item["datetime"] for item in items if item.get("datetime"))
    for item in items:
        for band in REQUIRED_BANDS:
            details = item.get("relevant_assets", {}).get(band, [])
            relevant_keys[band].update(detail["key"] for detail in details)
            cog_keys[band].update(detail["key"] for detail in details if detail.get("cog_likely"))
        if item.get("mgrs_tile"):
            mgrs_tiles.add(str(item["mgrs_tile"]))
    required_present = {band: bool(relevant_keys[band]) for band in REQUIRED_BANDS}
    complete_items = sum(
        all(item.get("relevant_assets", {}).get(band) for band in REQUIRED_BANDS) for item in items
    )
    return {
        "year": year,
        "candidate_observations": len(items),
        "date_range": {"min": dates[0], "max": dates[-1]} if dates else None,
        "cloud_cover": _cloud_stats(items),
        "intersecting_mgrs_tiles": sorted(mgrs_tiles),
        "relevant_asset_keys": {band: sorted(keys) for band, keys in relevant_keys.items()},
        "cog_relevant_asset_keys": {band: sorted(keys) for band, keys in cog_keys.items()},
        "required_assets_present": required_present,
        "all_required_future_assets_available": all(required_present.values()),
        "all_required_cog_assets_available": all(bool(cog_keys[band]) for band in REQUIRED_BANDS),
        "items_with_all_required_assets": complete_items,
    }


def _item_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("datetime") or ""), str(item["id"]))


def discover(config: ProjectConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    catalog = Client.open(config.stac_endpoint)
    all_items: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for year, (start, end) in config.annual_august_intervals().items():
        search = catalog.search(
            collections=[config.collection],
            bbox=config.aoi.as_list(),
            datetime=f"{start}/{end}",
        )
        year_items = [serialise_item(item, year) for item in search.items()]
        year_items.sort(key=_item_sort_key)
        all_items.extend(year_items)
        summaries.append(summarise_year(year_items, year))
        print_summary(summaries[-1])
    return all_items, summaries


def _choose_representative(
    items: list[dict[str, Any]], preferred_year: int = 2026
) -> dict[str, Any] | None:
    candidates = [item for item in items if item["year"] == preferred_year]
    if not candidates:
        candidates = items
    complete = [
        item
        for item in candidates
        if all(item.get("relevant_assets", {}).get(band) for band in REQUIRED_BANDS)
    ]
    candidates = complete or candidates
    return sorted(candidates, key=_item_sort_key)[0] if candidates else None


def remote_partial_read(item: dict[str, Any], band: str = "red") -> dict[str, Any]:
    choices = item.get("relevant_assets", {}).get(band, [])
    if not choices:
        raise RuntimeError(f"No {band} asset found on representative item {item['id']}")
    key = choices[0]["key"]
    asset = choices[0]
    href = asset["href"]
    if not asset.get("cog_likely"):
        raise RuntimeError(f"Selected asset {key} is not identified as a likely COG")

    # These options prevent directory probing and make GDAL use HTTP range reads.
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_USE_HEAD="NO"):
        with rasterio.open(href) as dataset:
            center_x = dataset.bounds.left + (dataset.bounds.right - dataset.bounds.left) / 2
            center_y = dataset.bounds.bottom + (dataset.bounds.top - dataset.bounds.bottom) / 2
            center_row, center_col = dataset.index(center_x, center_y)
            size = 32
            row_off = max(0, min(center_row - size // 2, dataset.height - size))
            col_off = max(0, min(center_col - size // 2, dataset.width - size))
            window = Window(col_off, row_off, min(size, dataset.width), min(size, dataset.height))
            values = dataset.read(
                1,
                window=window,
                out_shape=(int(window.height), int(window.width)),
                resampling=Resampling.nearest,
            )
            nodata = dataset.nodata
            valid = values if nodata is None else values[values != nodata]
            return {
                "item_id": item["id"],
                "asset_key": key,
                "href": href,
                "crs": str(dataset.crs) if dataset.crs else None,
                "width": dataset.width,
                "height": dataset.height,
                "transform": list(dataset.transform),
                "dtype": dataset.dtypes[0],
                "nodata": nodata,
                "block_shapes": [list(shape) for shape in dataset.block_shapes],
                "test_window": {
                    "col_off": int(window.col_off),
                    "row_off": int(window.row_off),
                    "width": int(window.width),
                    "height": int(window.height),
                },
                "valid_pixel_count": int(valid.size),
                "min": float(valid.min()) if valid.size else None,
                "max": float(valid.max()) if valid.size else None,
                "remote_range_read": True,
                "full_raster_read": False,
            }


def print_summary(summary: dict[str, Any]) -> None:
    stats = summary["cloud_cover"] or {}
    print(
        f"{summary['year']}: {summary['candidate_observations']} observations; "
        f"dates={summary['date_range']}; "
        f"cloud(min/median/max)={stats.get('min')}/{stats.get('median')}/{stats.get('max')}; "
        f"MGRS={','.join(summary['intersecting_mgrs_tiles']) or '-'}; "
        f"required_assets={summary['all_required_future_assets_available']}"
    )


def run(config_path: str | Path, inventory_dir: str | Path) -> dict[str, Any]:
    config = load_config(config_path)
    items, summaries = discover(config)
    representative = _choose_representative(items)
    cog_read = None
    cog_error = None
    if representative:
        try:
            cog_read = remote_partial_read(representative)
        except Exception as exc:  # noqa: BLE001 - preserve exact driver failure in output
            cog_error = {"type": type(exc).__name__, "message": str(exc)}
            print(f"Remote COG read failed: {type(exc).__name__}: {exc}")
    else:
        cog_error = {"type": "RuntimeError", "message": "No candidate observations returned"}

    output_dir = Path(inventory_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "stac-items.json").write_text(
        json.dumps(
            {"study_area_id": config.study_area_id, "items": items}, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    output = {
        "study_area_id": config.study_area_id,
        "stac_endpoint": config.stac_endpoint,
        "collection": config.collection,
        "aoi_bbox": config.aoi.as_list(),
        "requested_years": list(config.analysis_years),
        "requested_window": (
            f"month={config.month}, days={config.window_start_day}-{config.window_end_day}"
        ),
        "benchmark_years": list(config.benchmark_years),
        "years": summaries,
        "representative_item": representative["id"] if representative else None,
        "remote_partial_read": cog_read,
        "remote_partial_read_error": cog_error,
    }
    (output_dir / "stac-summary.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--inventory-dir", type=Path, default=Path("data/inventory"))
    args = parser.parse_args()
    run(args.config, args.inventory_dir)


if __name__ == "__main__":
    main()
