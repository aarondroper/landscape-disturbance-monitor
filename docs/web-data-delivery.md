# Static web data delivery

This builder packages analytical outputs for the frontend. The
package is static JSON and GeoJSON; it does not require an API, database,
network access, React, or MapLibre.

Build it locally with:

```bash
python -m landscape_monitor.build_web_data
```

The ignored outputs are written under `data/derived/web-delivery/data/`:

- `disturbances.geojson` contains the 80 WGS84 disturbance features and a
  compact browser property whitelist.
- `disturbance-timeseries.json` contains 10 annual NBR/recovery observations
  per disturbance, including coverage and contextual NDVI fields.
- `summary.json` contains project facts, landscape annual statistics, coverage
  counts, 2026 values, and structured limitation flags.
- `data-manifest.json` records schemas, payload checksums, sizes, source paths,
  years, CRS, and deterministic build assumptions.

The original analytical disturbance topology is retained. No geometric
simplification, smoothing, buffering, reprojection for editing, or geometry
repair is used. The rejected 20 m simplification experiment exceeded the area
QA limits and made one transformed feature invalid. Delivery GeoJSON applies
only coordinate rounding: five longitude/latitude decimal places are tried
first, with one permitted six-decimal retry if the validity and area gate
fails. The analytical `area_ha` property remains authoritative and is not
recomputed from delivery geometry.

Display-oriented numbers are rounded deterministically: areas to two decimal
places and NBR, dNBR, recovery, and fractions to four. Null remains null.
Coverage states are preserved as `GOOD`, `USABLE_WITH_COVERAGE_FLAG`, or
`POOR`; recovery values are unbounded spectral movement toward the NBR
baseline, not ecological recovery. NDVI is contextual only, and NDVI recovery
is not included.

The files are intended for static hosting and browser transfer. Gzip sizes are
reported diagnostically by the build command, but `.gz` assets are not created
by this package.
