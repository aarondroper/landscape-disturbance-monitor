# Static deployment

## Architecture

The application is a static split deployment:

```text
React/MapLibre shell  ->  Cloudflare Pages
Generated JSON/COGs   ->  Cloudflare R2 object storage
```

There is no project backend or database. The frontend shell is deployed at
[`https://landscape-disturbance-monitor.pages.dev`](https://landscape-disturbance-monitor.pages.dev).
The current public asset origin is:

```text
https://pub-89be2388b48b4d5ea68476d051c872ce.r2.dev/
```

The application uses the configurable `VITE_GEO_ASSET_BASE_URL`, so the
object-storage provider is not part of frontend runtime logic.

## Local development

Generated assets remain local under `data/derived/web-delivery/`. Vite serves
that directory read-only under `/geo/`. Its small middleware supports JSON and
GeoJSON responses plus HTTP byte ranges for local COG access.

```bash
cd web
npm ci
npm run dev
```

The local default is `VITE_GEO_ASSET_BASE_URL=/geo/`. Preview uses the same
middleware:

```bash
npm run build
npm run preview
```

## Static delivery package

The generated package keeps relative paths stable:

```text
data/       disturbance geometry, summaries, time series, manifests
imagery/    benchmark-year RGB COGs
rasters/    annual NBR, recovery, and fixed dNBR COGs
```

The package is generated locally, validated, and uploaded as a unit. It is
not committed to Git.

## Browser imagery COGs

Browser RGB imagery is delivered as tiled EPSG:3857 Cloud Optimized GeoTIFFs
with 256 × 256 internal blocks and overviews. The RGB COGs use explicit
three-band uint8 nodata handling; invalid pixels remain transparent through
the delivery mask/nodata convention. The browser protocol reads them through
HTTP Range requests.

The RGB workflow is separate from the canonical 20 m analytical grid and
serves presentation imagery only.

## Analytical raster COGs

The analytical browser package contains annual NBR COGs, annual spectral-
recovery COGs, and one fixed 2017→2018 dNBR COG. They are single-band
float32 EPSG:3857 COGs with internal masks and `-9999.0` output nodata.

Continuous values use normalized bilinear reprojection with a separate
nearest-neighbour validity mask. Source nodata is not interpolated into valid
pixels and missing observations are not filled. Raw recovery values remain
unbounded; display colorization occurs in the frontend.

## JSON and GeoJSON

The static data package contains:

- WGS84 disturbance GeoJSON with stable disturbance IDs;
- compact disturbance time-series observations;
- project and landscape summaries; and
- deterministic manifests with source relationships, metadata, hashes, and
  delivery paths.

Disturbance topology is retained. Delivery applies only QA-gated coordinate
rounding; analytical `area_ha` values remain authoritative.

## Range and CORS requirements

The production object store must provide:

- public read access to the generated package;
- `206 Partial Content` responses for byte ranges;
- `Content-Range` and `Accept-Ranges: bytes` headers;
- CORS for the exact frontend origin, `GET` and `HEAD`, and the `Range`
  request header;
- exposed response headers such as `Content-Length`, `Content-Range`, and
  `ETag`; and
- appropriate JSON, GeoJSON, and `image/tiff` content types.

See [`deploy/r2-cors.example.json`](../deploy/r2-cors.example.json) for a
non-secret example. Wildcard origins are not recommended for production.

## Production deployment

Set the public asset origin when building the frontend shell:

```bash
VITE_GEO_ASSET_BASE_URL=https://pub-89be2388b48b4d5ea68476d051c872ce.r2.dev/ npm run build
```

Upload the contents of `data/derived/web-delivery/` without changing relative
paths, then deploy the resulting frontend shell to Pages.

Recommended validation order:

1. Run `python -m landscape_monitor.validate_web_delivery`.
2. Verify a representative COG returns `206` for `Range: bytes=0-99`.
3. Verify CORS from the deployed Pages origin.
4. Build and deploy the frontend shell.
5. Run a browser smoke test for Compare, Disturbance, and Recovery.

The current `r2.dev` origin is operational. A custom R2 domain remains a
future hardening option for long-term infrastructure.
