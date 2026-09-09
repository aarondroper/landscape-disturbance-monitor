# Generated data

- `inventory/` contains generated STAC discovery and remote-COG provenance
  output from `python -m landscape_monitor.stac_probe`.
- `derived/prototype/` contains generated August composite, NBR, and dNBR
  prototype outputs from `python -m landscape_monitor.build_composite_prototype`.
- `derived/disturbance/` contains generated disturbance rasters, diagnostics,
  GeoJSON, and summaries from `python -m landscape_monitor.build_disturbance`.
- `derived/annual/<year>/` contains the explicit single-year annual NBR/NDVI
  outputs and one lightweight QA image from milestone 4A.
- `.tmp/annual/<year>/` is a run-owned workspace for AOI-only derived
  acquisition rasters. It is cleaned after each run unless
  `--keep-temp-on-error` is supplied; no raw Sentinel-2 scenes are cached.

These files are reproducible and intentionally excluded from Git. The local
directories are retained with marker files so the output layout remains clear
after checkout.
