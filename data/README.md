# Generated data

- `inventory/` contains generated STAC discovery and remote-COG provenance
  output from `python -m landscape_monitor.stac_probe`.
- `derived/prototype/` contains generated August composite, NBR, and dNBR
  prototype outputs from `python -m landscape_monitor.build_composite_prototype`.
- `derived/disturbance/` contains generated disturbance rasters, diagnostics,
  GeoJSON, and summaries from `python -m landscape_monitor.build_disturbance`.
- `derived/annual/<year>/` contains the explicit single-year annual NBR/NDVI
  outputs and one lightweight QA image from milestone 4A.
- `derived/recovery/` contains the local milestone-5A NBR spectral-recovery
  rasters, deterministic object/landscape JSON, and analytical QA figures.
- `derived/web-imagery/<year>/` contains generated 10 m RGB reflectance masters,
  RGBA Cloud Optimized GeoTIFFs, and lightweight RGB quicklooks for milestone
  6C. `rgb-imagery-summary.json` records the five-year source, processing,
  coverage, display, and resource provenance.
- `derived/web-imagery/` is presentation imagery only. It does not replace the
  20 m analytical NBR/recovery grid, and it uses one shared display treatment
  for benchmark years 2017, 2018, 2020, 2023, and 2026.
- `derived/web-delivery/` contains milestone-6D generated EPSG:3857, three-band
  RGB browser COGs, quicklook comparisons, and `imagery-manifest.json`. These
  are separate from the canonical `web-imagery/` masters and use explicit
  `[255,255,255]` nodata without an alpha band. All generated delivery files
  remain Git-ignored.
- `derived/web-delivery/data/` contains the milestone-6E static vector/JSON
  package: unsimplified WGS84 disturbance GeoJSON with QA-gated coordinate
  rounding, compact disturbance time series, landscape summary, and a
  deterministic manifest. Its analytical `area_ha` values remain authoritative.
- `derived/annual/build-status.json` records the latest non-dry-run explicit
  annual batch attempt; it is advisory and does not replace output validation.
- `derived/diagnostics/` contains local coverage and reflectance-treatment
  audit outputs. Diagnostic GeoTIFFs, PNGs, and JSON reports are ignored by
  Git and must not be treated as production annual outputs.
- `.tmp/annual/<year>/` is a run-owned workspace for AOI-only derived
  acquisition rasters. It is cleaned after each run unless
  `--keep-temp-on-error` is supplied; no raw Sentinel-2 scenes are cached.

These files are reproducible and intentionally excluded from Git. The local
directories are retained with marker files so the output layout remains clear
after checkout.
