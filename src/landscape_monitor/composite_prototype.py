"""Small, deterministic Sentinel-2 compositing building blocks.

The functions in this module are deliberately independent of Earth Search so
that the numerical and grouping behavior can be tested with small arrays.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import Affine, from_origin
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window

from .config import BBox

ANALYSIS_CRS = "EPSG:32633"
ANALYSIS_RESOLUTION = 20.0
SCL_INVALID_CLASSES = frozenset({0, 1, 3, 8, 9, 10, 11})
FLOAT_NODATA = -9999.0
COUNT_NODATA = 65535
PIXEL_AREA_HECTARES = ANALYSIS_RESOLUTION * ANALYSIS_RESOLUTION / 10_000


@dataclass(frozen=True)
class AnalysisGrid:
    """The common, north-up output grid used for both annual composites."""

    crs: str
    resolution: float
    transform: Affine
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    aoi_mask: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.height, self.width


def create_analysis_grid(
    aoi: BBox,
    resolution: float = ANALYSIS_RESOLUTION,
    crs: str = ANALYSIS_CRS,
) -> AnalysisGrid:
    """Transform a WGS84 bbox and snap its bounds outward to a regular grid."""
    if resolution <= 0:
        raise ValueError("resolution must be positive")
    west, south, east, north = transform_bounds(
        "EPSG:4326", crs, aoi.west, aoi.south, aoi.east, aoi.north, densify_pts=21
    )
    left = math.floor(west / resolution) * resolution
    bottom = math.floor(south / resolution) * resolution
    right = math.ceil(east / resolution) * resolution
    top = math.ceil(north / resolution) * resolution
    width = int(round((right - left) / resolution))
    height = int(round((top - bottom) / resolution))
    transform = from_origin(left, top, resolution, resolution)

    aoi_geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [aoi.west, aoi.south],
                [aoi.east, aoi.south],
                [aoi.east, aoi.north],
                [aoi.west, aoi.north],
                [aoi.west, aoi.south],
            ]
        ],
    }
    # geometry_mask expects geometry coordinates in the grid CRS.  Transform
    # the four bbox corners without introducing a shapely dependency.
    from rasterio.warp import transform as transform_coordinates

    xs, ys = transform_coordinates(
        "EPSG:4326",
        crs,
        [aoi.west, aoi.east, aoi.east, aoi.west, aoi.west],
        [aoi.south, aoi.south, aoi.north, aoi.north, aoi.south],
    )
    aoi_geometry["coordinates"] = [[[x, y] for x, y in zip(xs, ys, strict=True)]]
    aoi_mask = geometry_mask(
        [aoi_geometry], out_shape=(height, width), transform=transform, invert=True
    )
    return AnalysisGrid(
        crs=crs,
        resolution=resolution,
        transform=transform,
        width=width,
        height=height,
        bounds=(left, bottom, right, top),
        aoi_mask=aoi_mask,
    )


def valid_scl_mask(scl: np.ndarray) -> np.ndarray:
    """Return the prescribed pixel-valid mask for a 20 m SCL array."""
    valid = np.ones(scl.shape, dtype=bool)
    for value in SCL_INVALID_CLASSES:
        valid &= scl != value
    return valid


def apply_scale_offset(
    samples: np.ndarray, scale: float | None, offset: float | None
) -> np.ndarray:
    """Convert integer samples to physical values using STAC raster metadata."""
    result = np.asarray(samples, dtype=np.float32)
    return result * (1.0 if scale is None else float(scale)) + (
        0.0 if offset is None else float(offset)
    )


def calculate_nbr(
    nir: np.ndarray, swir2: np.ndarray, valid_mask: np.ndarray | None = None
) -> np.ndarray:
    """Calculate NBR, returning NaN for nodata, bad denominators, or invalid pixels."""
    nir_float = np.asarray(nir, dtype=np.float32)
    swir_float = np.asarray(swir2, dtype=np.float32)
    denominator = nir_float + swir_float
    valid = np.isfinite(nir_float) & np.isfinite(swir_float) & np.isfinite(denominator)
    valid &= denominator != 0
    # Negative reflectance is outside the physical domain of this normalized
    # index and occurs for some low-signal pixels after an authoritative -0.1
    # STAC offset is applied.  Excluding it avoids unstable ratios near zero.
    valid &= (nir_float >= 0) & (swir_float >= 0)
    if valid_mask is not None:
        valid &= valid_mask
    nbr = np.full(nir_float.shape, np.nan, dtype=np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        nbr[valid] = (nir_float[valid] - swir_float[valid]) / denominator[valid]
    nbr[~np.isfinite(nbr)] = np.nan
    return nbr


def calculate_ndvi(
    nir: np.ndarray, red: np.ndarray, valid_mask: np.ndarray | None = None
) -> np.ndarray:
    """Calculate NDVI, returning NaN for nodata, bad denominators, or invalid pixels."""
    nir_float = np.asarray(nir, dtype=np.float32)
    red_float = np.asarray(red, dtype=np.float32)
    denominator = nir_float + red_float
    valid = np.isfinite(nir_float) & np.isfinite(red_float) & np.isfinite(denominator)
    valid &= denominator != 0
    valid &= (nir_float >= 0) & (red_float >= 0)
    if valid_mask is not None:
        valid &= valid_mask
    ndvi = np.full(nir_float.shape, np.nan, dtype=np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi[valid] = (nir_float[valid] - red_float[valid]) / denominator[valid]
    ndvi[~np.isfinite(ndvi)] = np.nan
    return ndvi


def median_composite(observations: Sequence[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Return per-pixel NaN-median and the number of contributing observations."""
    if not observations:
        raise ValueError("at least one observation is required")
    stack = np.asarray(observations, dtype=np.float32)
    valid_count = np.sum(np.isfinite(stack), axis=0, dtype=np.uint16)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        composite = np.nanmedian(stack, axis=0).astype(np.float32)
    composite[valid_count == 0] = np.nan
    return composite, valid_count


def mosaic_valid_pixels(
    arrays: Sequence[np.ndarray], masks: Sequence[np.ndarray]
) -> tuple[np.ndarray, np.ndarray]:
    """Mosaic arrays with deterministic first-valid-pixel precedence.

    Callers provide arrays in their chosen deterministic order.  A later array
    fills only pixels not already filled by an earlier valid array; valid
    overlaps are never averaged.
    """
    if len(arrays) != len(masks) or not arrays:
        raise ValueError("arrays and masks must be non-empty and have equal length")
    result = np.full(arrays[0].shape, np.nan, dtype=np.float32)
    filled = np.zeros(arrays[0].shape, dtype=bool)
    for array, mask in zip(arrays, masks, strict=True):
        valid = np.asarray(mask, dtype=bool) & np.isfinite(array) & ~filled
        result[valid] = np.asarray(array, dtype=np.float32)[valid]
        filled[valid] = True
    return result, filled


def dnbr(pre_nbr: np.ndarray, post_nbr: np.ndarray) -> np.ndarray:
    """Return pre-fire minus post-fire NBR, with NaN-safe validity."""
    pre = np.asarray(pre_nbr, dtype=np.float32)
    post = np.asarray(post_nbr, dtype=np.float32)
    result = np.full(pre.shape, np.nan, dtype=np.float32)
    valid = np.isfinite(pre) & np.isfinite(post)
    result[valid] = pre[valid] - post[valid]
    return result


def area_hectares_at_least(values: np.ndarray, threshold: float) -> dict[str, float | int]:
    """Count valid pixels at or above a diagnostic threshold and convert to ha."""
    valid = np.isfinite(values)
    count = int(np.count_nonzero(valid & (values >= threshold)))
    return {"pixel_count": count, "area_hectares": count * PIXEL_AREA_HECTARES}


def distribution(values: np.ndarray) -> dict[str, float | int | None]:
    """Return the requested descriptive distribution for finite values."""
    finite = np.asarray(values)[np.isfinite(values)]
    if not finite.size:
        return {
            "count": 0,
            "min": None,
            "p01": None,
            "p05": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
            "mean": None,
            "std": None,
        }
    percentiles = np.percentile(finite, [1, 5, 25, 50, 75, 90, 95, 99])
    return {
        "count": int(finite.size),
        "min": float(np.min(finite)),
        "p01": float(percentiles[0]),
        "p05": float(percentiles[1]),
        "p25": float(percentiles[2]),
        "median": float(percentiles[3]),
        "p75": float(percentiles[4]),
        "p90": float(percentiles[5]),
        "p95": float(percentiles[6]),
        "p99": float(percentiles[7]),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "std": float(np.std(finite)),
    }


def valid_count_distribution(
    counts: np.ndarray, aoi_mask: np.ndarray
) -> dict[str, float | int | None]:
    """Summarise valid observation counts inside the AOI, including zeroes."""
    values = np.asarray(counts)[aoi_mask]
    if not values.size:
        return {
            "count": 0,
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
            "max": None,
            "zero_count": 0,
        }
    return {
        "count": int(values.size),
        "min": int(np.min(values)),
        "p25": float(np.percentile(values, 25)),
        "median": float(np.percentile(values, 50)),
        "p75": float(np.percentile(values, 75)),
        "max": int(np.max(values)),
        "zero_count": int(np.count_nonzero(values == 0)),
    }


def is_usable_acquisition(record: Mapping[str, Any]) -> bool:
    """Return whether a grouped acquisition contributed any valid AOI pixel."""
    return record["valid_pixel_count"] > 0


def group_acquisition_items(items: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group inventory Items by UTC calendar date and sort IDs deterministically."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        value = item.get("datetime")
        if not value:
            raise ValueError(f"Item {item.get('id')} has no datetime")
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        groups.setdefault(parsed.date().isoformat(), []).append(item)
    for group in groups.values():
        group.sort(key=lambda item: (str(item.get("mgrs_tile") or ""), str(item["id"])))
    return dict(sorted(groups.items()))


def source_window(dataset: rasterio.DatasetReader, grid: AnalysisGrid) -> Window:
    """Return a small outward-rounded source window covering the output grid."""
    left, bottom, right, top = transform_bounds(grid.crs, dataset.crs, *grid.bounds, densify_pts=21)
    window = rasterio.windows.from_bounds(left, bottom, right, top, transform=dataset.transform)
    col_start = max(0, math.floor(window.col_off) - 1)
    row_start = max(0, math.floor(window.row_off) - 1)
    col_stop = min(dataset.width, math.ceil(window.col_off + window.width) + 1)
    row_stop = min(dataset.height, math.ceil(window.row_off + window.height) + 1)
    if col_stop <= col_start or row_stop <= row_start:
        raise ValueError("analysis grid does not intersect source dataset")
    return Window(col_start, row_start, col_stop - col_start, row_stop - row_start)


def read_remote_asset_to_grid(
    asset: dict[str, Any],
    grid: AnalysisGrid,
    *,
    scale: float | None = None,
    offset: float | None = None,
    resampling: rasterio.enums.Resampling = rasterio.enums.Resampling.average,
) -> np.ndarray:
    """Read only the source window intersecting the AOI and reproject to grid."""
    href = asset.get("href")
    if not href or not str(href).startswith(("https://", "http://")):
        raise ValueError(f"Expected an HTTPS COG href, got {href!r}")
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_USE_HEAD="NO",
        GDAL_HTTP_TIMEOUT="60",
        GDAL_HTTP_MAX_RETRY="2",
        GDAL_HTTP_RETRY_DELAY="1",
        GDAL_CACHEMAX=256,
    ):
        with rasterio.open(str(href)) as dataset:
            window = source_window(dataset, grid)
            raw = dataset.read(1, window=window, masked=False)
            source_nodata = dataset.nodata
            if scale is None or offset is None:
                bands = asset.get("raster:bands", []) or []
                band_metadata = bands[0] if bands else {}
                scale = band_metadata.get("scale", scale)
                offset = band_metadata.get("offset", offset)
            source = apply_scale_offset(raw, scale, offset)
            source_fill = -999999.0
            if source_nodata is not None:
                source[raw == source_nodata] = source_fill
            destination = np.full(grid.shape, source_fill, dtype=np.float32)
            reproject(
                source=source,
                destination=destination,
                src_transform=dataset.window_transform(window),
                src_crs=dataset.crs,
                src_nodata=source_fill,
                dst_transform=grid.transform,
                dst_crs=grid.crs,
                dst_nodata=source_fill,
                resampling=resampling,
            )
    destination[destination == source_fill] = np.nan
    return destination


def read_asset_metadata(asset: dict[str, Any]) -> dict[str, float | None]:
    """Extract authoritative scale/offset from a serialized STAC asset."""
    bands = asset.get("raster:bands", []) or []
    metadata = bands[0] if bands else {}
    return {
        "scale": float(metadata["scale"]) if metadata.get("scale") is not None else None,
        "offset": float(metadata["offset"]) if metadata.get("offset") is not None else None,
    }


def read_item_indices(
    item: dict[str, Any],
    grid: AnalysisGrid,
    asset_getter: Any,
) -> dict[str, np.ndarray]:
    """Read one item and calculate NBR/NDVI on the common grid.

    NIR, red, and SWIR2 are averaged when reprojected to 20 m. SCL uses
    nearest-neighbour. NBR validity intentionally does not depend on red so
    that the approved 2017/2018 NBR prototype semantics remain unchanged.
    """
    bands = ("nir", "red", "swir2", "scl")
    assets = {band: asset_getter(item, band) for band in bands}
    metadata = {band: read_asset_metadata(assets[band]) for band in bands}
    for band in ("nir", "red", "swir2"):
        if metadata[band]["scale"] is None:
            raise ValueError(
                f"Item {item['id']} lacks STAC raster scale metadata for {band}; "
                "refresh the inventory with stac_probe.py"
            )
    # Deliberately read one band at a time.  The annual builder processes one
    # item at a time and must not multiply source/destination raster buffers
    # with a thread pool.  The three float32 reflectance arrays are retained
    # only until both indices for this one item have been calculated.
    reflectance: dict[str, np.ndarray] = {}
    for band in ("nir", "red", "swir2"):
        reflectance[band] = read_remote_asset_to_grid(
            assets[band],
            grid,
            **metadata[band],
            resampling=Resampling.average,
        )
    scl = read_remote_asset_to_grid(
        assets["scl"],
        grid,
        scale=1.0,
        offset=0.0,
        resampling=Resampling.nearest,
    )
    scl = np.where(np.isfinite(scl), np.rint(scl), 0).astype(np.uint8)
    scl_valid = valid_scl_mask(scl) & grid.aoi_mask
    nbr_mask = scl_valid & np.isfinite(reflectance["nir"]) & np.isfinite(reflectance["swir2"])
    ndvi_mask = scl_valid & np.isfinite(reflectance["nir"]) & np.isfinite(reflectance["red"])
    nbr = calculate_nbr(reflectance["nir"], reflectance["swir2"], nbr_mask)
    ndvi = calculate_ndvi(reflectance["nir"], reflectance["red"], ndvi_mask)
    return {
        "nbr": nbr,
        "nbr_mask": nbr_mask & np.isfinite(nbr),
        "ndvi": ndvi,
        "ndvi_mask": ndvi_mask & np.isfinite(ndvi),
        "scale_offset": metadata,
    }
