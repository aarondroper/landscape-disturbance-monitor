# Browser RGB imagery delivery

This builder converts local RGB presentation masters into static
browser-delivery Cloud Optimized GeoTIFFs. It is a local packaging step only:
it does not query STAC, read Sentinel-2 remotely, rebuild reflectance
composites, or change analytical, disturbance, or recovery products.

The canonical products remain in `data/derived/web-imagery/<year>/`:

- `rgb-reflectance.tif` is the physical-reflectance presentation master.
- `rgb-web.tif` is the EPSG:32633 RGBA presentation product.

The browser assets are separate generated files in
`data/derived/web-delivery/imagery/<year>/rgb.tif`. They are EPSG:3857 because
the intended serverless MapLibre COG protocol does not perform arbitrary raster
reprojection. One grid is derived from the common EPSG:32633 source
grid with Rasterio/GDAL and reused for every benchmark year:

```text
CRS:       EPSG:3857
bounds:    [1683036.2196353192, 8825702.196670972,
            1737091.3972225846, 8878439.991785591]
size:      2544 × 2482
transform: | 21.248104397509934, 0, 1683036.2196353192 |
           | 0, -21.248104397509934, 8878439.991785591 |
           | 0, 0, 1 |
pixel:     21.248104397509934 EPSG:3857 map units
```

At this latitude that map-unit spacing is approximately native 10 m ground
detail; it is not an assertion that Web Mercator map units equal ground metres.
All five COGs use three uint8 RGB bands, 256×256 internal tiles, DEFLATE,
internal overviews `[2, 4, 8, 16]`, and RGB photometric/color interpretation.
The fixed display transform is unchanged: black `0.01`, white `0.22`,
gamma `1.0`. Reflectance is reprojected with average resampling and its
validity mask with nearest-neighbour resampling before rendering.

The browser protocol does not depend on a separate alpha band. Nodata is
explicitly `255` in every band, so invalid pixels are `[255,255,255]`. Since a
valid pixel can naturally render all-white under the fixed stretch, valid
`[255,255,255]` pixels are deterministically remapped to `[254,254,254]`.
Pixels with only one or two channels equal to 255 are retained unchanged.

`imagery-manifest.json` contains relative asset paths, the frozen grid,
display parameters, valid/nodata fractions, source hashes, file sizes, COG
metadata, and resource telemetry. The command requires one explicit year and
supports only `2017`, `2018`, `2020`, `2023`, and `2026`:

```bash
python -m landscape_monitor.build_web_imagery --year 2017
```

Static hosting must preserve byte-range requests for the COG files. Quicklook
comparisons are generated under `data/derived/web-delivery/quicklooks/` for
local QA and are not frontend implementation. The accepted low source signal
in 2023 and 2026 remains visible; no year-specific stretch or correction is
applied.
