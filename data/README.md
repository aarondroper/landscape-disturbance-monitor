# Generated data

- `inventory/` contains generated STAC discovery and remote-COG provenance
  output from `python -m landscape_monitor.stac_probe`.
- `derived/prototype/` contains generated August composite, NBR, and dNBR
  prototype outputs from `python -m landscape_monitor.build_composite_prototype`.
- `derived/disturbance/` contains generated disturbance rasters, diagnostics,
  GeoJSON, and summaries from `python -m landscape_monitor.build_disturbance`.

These files are reproducible and intentionally excluded from Git. The local
directories are retained with marker files so the output layout remains clear
after checkout.
