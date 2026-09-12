# Analytical raster web delivery

This builder packages the analytical rasters for browser delivery.
The canonical analysis remains EPSG:32633 on the 20 m, 1266 × 1233 grid and
continues to be authoritative for exact numerical analysis. Browser derivatives
use one separately derived EPSG:3857 analytical grid; they do not reuse the
10 m RGB imagery grid.

The package contains ten annual NBR COGs, ten annual NBR spectral-recovery
COGs, and one fixed `2017 → 2018` dNBR COG. Every layer is a tiled, DEFLATE-
compressed, single-band float32 Cloud Optimized GeoTIFF with internal
overviews and an internal validity mask. Continuous values use normalized
bilinear reprojection with a separate nearest-neighbour validity reprojection,
so source nodata is not interpolated into valid output and missing observations
are not filled. Output nodata is `-9999.0`, while transparency is read from the
internal mask.

Raw analytical values are preserved. Recovery is unbounded and remains masked
to the retained disturbance footprint; it is not clamped to `[0, 1]`. The
dNBR layer is a spectral NBR change layer, not an authoritative burn-severity
product. Fragmented later-year coverage remains visible through the masks.
Browser colorization is deferred to the frontend and is not stored in these
COGs.

Build locally with:

```bash
python -m landscape_monitor.build_web_rasters
python -m landscape_monitor.build_web_rasters --force
```

The command reads only local sources and writes generated COGs,
diagnostic quicklooks, and `data/derived/web-delivery/raster-manifest.json`.
The intended deployment is static HTTP/object storage with byte-range support,
consumed by MapLibre GL JS through `@geomatico/maplibre-cog-protocol`.
