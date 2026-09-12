# Generated data

- `inventory/` contains generated STAC discovery and remote-COG provenance
  output from `python -m landscape_monitor.stac_probe`.
- `derived/prototype/` contains generated August composite, NBR, and dNBR
  prototype outputs from `python -m landscape_monitor.build_composite_prototype`.
- `derived/disturbance/` contains generated disturbance rasters, diagnostics,
  GeoJSON, and summaries from `python -m landscape_monitor.build_disturbance`.
- `derived/annual/<year>/` contains the explicit single-year annual NBR/NDVI
  outputs and one lightweight QA image.
- `derived/recovery/` contains the local NBR spectral-recovery
  rasters, deterministic object/landscape JSON, and analytical QA figures.
- `derived/web-imagery/<year>/` contains generated 10 m RGB reflectance masters,
  RGBA Cloud Optimized GeoTIFFs, and lightweight RGB quicklooks.
  `rgb-imagery-summary.json` records the five-year source, processing,
  coverage, display, and resource provenance.
- `derived/web-imagery/` is presentation imagery only. It does not replace the
  20 m analytical NBR/recovery grid, and it uses one shared display treatment
  for benchmark years 2017, 2018, 2020, 2023, and 2026.
- `derived/web-delivery/` contains generated EPSG:3857, three-band
  RGB browser COGs, quicklook comparisons, and `imagery-manifest.json`. These
  are separate from the canonical `web-imagery/` masters and use explicit
  `[255,255,255]` nodata without an alpha band. All generated delivery files
  remain Git-ignored.
- `derived/web-delivery/data/` contains the static vector/JSON
  package: unsimplified WGS84 disturbance GeoJSON with QA-gated coordinate
  rounding, compact disturbance time series, landscape summary, and a
  deterministic manifest. Its analytical `area_ha` values remain authoritative.
- `derived/web-delivery/rasters/` contains single-band float32
  analytical COGs: annual NBR, unbounded disturbance-footprint recovery, and
  fixed 2017→2018 spectral dNBR. They use one EPSG:3857 grid derived from the
  canonical 20 m EPSG:32633 grid, internal masks, and browser-side colorization.
  `raster-manifest.json` records deterministic delivery metadata and QA; these
  COGs are visualization derivatives, not replacements for canonical sources.
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
