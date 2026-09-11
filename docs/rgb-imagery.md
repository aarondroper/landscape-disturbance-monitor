# Browser-oriented RGB imagery

Milestone 6C delivers presentation-only natural-color Sentinel-2 imagery for
the five benchmark years 2017, 2018, 2020, 2023, and 2026. It is separate from the approved 20 m
analytical NBR/NDVI and recovery products: RGB uses a fixed 10 m grid with
EPSG:32633 bounds `[506260, 6858580, 531580, 6883240]`, 2532 columns, and
2466 rows. The analytical grid remains 20 m and is not resampled here.

The workflow uses the existing Earth Search `sentinel-2-l2a` inventory and
groups the exact August 1–31 acquisition universe by UTC calendar date. For
each date it reads only AOI-intersecting windows of red, green, blue, and SCL
COGs, mosaics same-date tiles in deterministic `(MGRS tile, Item ID)` order,
and applies the existing SCL invalid classes `0, 1, 3, 8, 9, 10, 11`.
Spectral bands use the existing average resampling behavior; SCL uses nearest
neighbour. STAC scale/offset metadata is applied before reprojection.

RGB values are clamped to zero only for finite negative reflectance in this
visualization path. This is display handling, not analytical validity: the
analytical NBR/NDVI `REJECT` treatment and its products are unchanged. Each
channel is temporally median-composited in physical reflectance, independently
of the other channels, before rendering.

All five years use the identical final approved transform:

```text
black point = 0.01
white point = 0.22
gamma       = 1.0
```

There is no per-year percentile stretch, white balance, histogram equalization,
saturation boost, or sharpening. The rendered output is an RGBA COG with
internal tiling and overview pyramids; pixels with no valid composite RGB
observation are transparent rather than black. The reflectance master is a
generated intermediate and is not a browser asset.

The 6B comparison established that the brighter `0.01–0.22` transform improved
forest, shadow, and disturbance-detail legibility while preserving shared
cross-year comparability and negligible highlight clipping. The `0.30` value is
retained only as historical diagnostic rendering support; it is not a
production treatment.

Run one benchmark year explicitly:

```bash
python -m landscape_monitor.build_rgb_imagery --year 2017
python -m landscape_monitor.build_rgb_imagery --year 2018
python -m landscape_monitor.build_rgb_imagery --year 2020
python -m landscape_monitor.build_rgb_imagery --year 2023
python -m landscape_monitor.build_rgb_imagery --year 2026
```

The command requires `--year` and does not provide an implicit multi-year mode.
All outputs share the same CRS, bounds, transform, dimensions, 10 m pixel
alignment, tiled RGBA layout, DEFLATE compression, and internal overviews.
This makes the set suitable as the imagery backbone for future year switching
and synchronized swipe comparison. It does not build a frontend, tiles,
MapLibre integration, swipe interaction, or recovery web layers.

The configured production display is `black = 0.01`, `white = 0.22`,
`gamma = 1.0`. The local renderer can still create named diagnostic variants
from existing masters without changing project configuration; candidate or
historical diagnostic outputs cannot overwrite canonical products.

Visual QA found that 2023 and 2026 have very low source RGB signal and therefore
render much darker than 2017, 2018, and 2020 under the intentionally shared
treatment. This is documented as a source-quality caveat rather than corrected
with year-specific stretching; it does not alter the analytical NBR/recovery
products or the canonical georeferencing.
Run the local candidate renderer with:

```bash
python -m landscape_monitor.render_rgb --year 2017 \
  --white-point 0.22 --output-variant candidate-022
python -m landscape_monitor.render_rgb --year 2018 \
  --white-point 0.22 --output-variant candidate-022
python -m landscape_monitor.render_rgb --compare
```
