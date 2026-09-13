# Split static deployment

## Current deployment

Frontend: [https://landscape-disturbance-monitor.pages.dev](https://landscape-disturbance-monitor.pages.dev)

Assets: `https://pub-89be2388b48b4d5ea68476d051c872ce.r2.dev/`

Architecture: Cloudflare Pages frontend shell → public R2 JSON/GeoJSON/COGs.
The current `r2.dev` endpoint is operational and has validated HTTP Range and
CORS behavior for the deployed Pages origin.

## Architecture

The frontend is a static application shell hosted on Cloudflare Pages or an
equivalent ordinary static host. The generated geospatial package is hosted
separately in a public, range-capable Cloudflare R2 object store.

```text
frontend shell  ->  static app host / Cloudflare Pages
COG and JSON    ->  range-capable public R2 origin
```

This split is required because Cloud Optimized GeoTIFFs (COGs) depend on HTTP
byte-range requests. Cloudflare Pages static serving is not the chosen COG
origin because production COG delivery requires proper `206 Partial Content`
responses. The application uses the generic `VITE_GEO_ASSET_BASE_URL` setting,
so the object-storage provider is not part of runtime application logic.

## Local development

The generated package remains local at
`data/derived/web-delivery/`. Vite serves that directory read-only under
`/geo/`, including JSON/GeoJSON GETs and COG byte ranges. No upload or cloud
credentials are needed.

```bash
cd web
npm run dev
```

The default is `VITE_GEO_ASSET_BASE_URL=/geo/`. Vite preview also installs the
same local middleware for development/QA:

```bash
npm run build
npm run preview
```

Preview does not copy the generated package into `web/dist/`.

## Production build

Set the public asset origin when building the static shell. The current
deployment uses:

```bash
VITE_GEO_ASSET_BASE_URL=https://pub-89be2388b48b4d5ea68476d051c872ce.r2.dev/ npm run build
```

The frontend bundle contains the application shell only. All generated asset
paths retain their package-relative layout and are resolved through the shared
asset URL helper.

## R2/object-storage requirements

- public read access for the generated package;
- correct HTTP byte-range support, including `206`, `Content-Range`, and
  `Accept-Ranges: bytes`;
- CORS for the exact frontend origin, including `GET` and `HEAD` and the
  `Range` request header;
- useful response headers exposed to the browser; and
- appropriate content types, especially `image/tiff` for COGs and JSON/GeoJSON
  types for data files.

The contents of `data/derived/web-delivery/` should be uploaded under one
project prefix without changing the relative paths:

```text
landscape-disturbance-monitor/
├── imagery/
├── rasters/
├── data/
├── imagery-manifest.json
└── raster-manifest.json
```

For that layout, production configuration is:

```text
VITE_GEO_ASSET_BASE_URL=https://pub-89be2388b48b4d5ea68476d051c872ce.r2.dev/
```

See [`deploy/r2-cors.example.json`](../deploy/r2-cors.example.json) for a
non-secret CORS example. The current configuration allows the exact Pages
origin; do not use wildcard origins for the recommended production
configuration.

## Future hardening

The current `r2.dev` origin works and has validated HTTP Range/CORS behavior,
but a custom R2 domain is recommended before treating the asset endpoint as
long-term production infrastructure. No custom domain is currently
configured for this project.

## Deployment order

1. Validate the generated package:

   ```bash
   python -m landscape_monitor.validate_web_delivery
   ```

2. Upload the contents of `data/derived/web-delivery/` to the object-storage
   project prefix.
3. Verify a representative COG returns HTTP `206` for
   `Range: bytes=0-99`.
4. Verify the configured CORS response from the production frontend origin.
5. Build the frontend with the external asset base URL.
6. Deploy the frontend shell to the static app host.
7. Run a browser smoke test for Compare, Disturbance, and Recovery.

No credentials, account IDs, bucket names, or deployment commands are part of
this repository’s deployment configuration.
