# Data feasibility — initial probe

This document records the live probe run on 2026-09-09.

- Catalogue: Element 84 Earth Search v1
- Collection: `sentinel-2-l2a`
- Provisional WGS84 AOI: west `15.12`, south `61.86`, east `15.60`, north `62.08`
- Requested windows: August 1–31 for each year 2017–2026
- Benchmark years: 2017, 2018, 2020, 2023, 2026
- Planned future assets checked: blue, green, red, NIR, SWIR2/B12, SCL

## Live result

The probe returned 537 candidate Items across the ten requested August windows. Every
year returned observations, and every returned Item had all six required logical assets
available according to its STAC asset metadata.

| Year | Items | Item date range (UTC) | Cloud cover min / median / max (%) | MGRS tiles |
|---|---:|---|---:|---|
| 2017 | 17 | 2017-08-01 – 2017-08-30 | 12.077246 / 36.677447 / 94.597661 | 33VVJ, 33VWJ |
| 2018 | 68 | 2018-08-01 – 2018-08-31 | 9.092355 / 73.374019 / 100.0 | 33VVJ, 33VWJ |
| 2019 | 80 | 2019-08-01 – 2019-08-31 | 0.0 / 75.3258635 / 100.0 | 33VVJ, 33VWJ |
| 2020 | 72 | 2020-08-02 – 2020-08-30 | 0.524275 / 38.9875185 / 99.668455 | 33VVJ, 33VWJ |
| 2021 | 74 | 2021-08-02 – 2021-08-30 | 0.957914 / 84.699243 / 100.0 | 33VVJ, 33VWJ |
| 2022 | 38 | 2022-08-02 – 2022-08-30 | 0.006699 / 61.8231235 / 100.0 | 33VVJ, 33VWJ |
| 2023 | 38 | 2023-08-02 – 2023-08-30 | 0.266203 / 86.444995 / 99.999976 | 33VVJ, 33VWJ |
| 2024 | 38 | 2024-08-01 – 2024-08-31 | 14.573598 / 73.134479 / 99.99975 | 33VVJ, 33VWJ |
| 2025 | 54 | 2025-08-01 – 2025-08-31 | 6.340409 / 69.028121 / 100.0 | 33VVJ, 33VWJ |
| 2026 | 58 | 2026-08-01 – 2026-08-31 | 1.152857 / 66.387743 / 99.999821 | 33VVJ, 33VWJ |

The actual logical-to-asset-key mapping discovered was:

- blue: `blue`, `blue-jp2`
- green: `green`, `green-jp2`
- red: `red`, `red-jp2`
- NIR: `nir`, `nir-jp2`
- SWIR2 / B12: `swir22`, `swir22-jp2`
- SCL: `scl`, `scl-jp2`

The non-JP2 keys were advertised as `image/tiff; application=geotiff; profile=cloud-optimized`
and pointed to HTTPS Sentinel COG URLs. The JP2 alternatives were `image/jp2` and used
`s3://` hrefs. The `visual`/preview assets were not counted as individual reflectance bands.

## Remote partial-read test

The representative Item was `S2C_33VWJ_20260801_0_L2A` from August 2026. Rasterio opened
its remote `red` COG and read only a 32×32 window at pixel offset (5474, 5474). The read
returned 1,024 valid pixels, with values 2,664–6,079. Raster metadata was CRS `EPSG:32633`,
dimensions 10,980×10,980, dtype `uint16`, nodata `0`, transform origin `(499980, 6900000)`
with 10 m pixels, and 1,024×1,024 internal blocks. The configured GDAL `/vsicurl` access
used HTTP range-oriented remote access; no full raster read was performed.

## Architecture assessment

The Sentinel-2 L2A / Earth Search / HTTPS COG architecture is viable for the planned
partial-read workflow. The AOI intersects two MGRS tiles (`33VVJ`, `33VWJ`), so later
selection/compositing should retain tile identity. Scene-level cloud cover is frequently
high, especially in the later years; it should remain a diagnostic rather than a hard
selection rule because the planned SCL mask is still needed.

## Caveats

The AOI is a provisional rectangle, not a final scientific fire boundary. The probe
records scene-level cloud cover but does not use it as a hard filter; later processing
will require pixel-level SCL masking. No index, composite, disturbance, recovery, or
web output is produced by this milestone.
