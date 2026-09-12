# Frontend foundation

Milestone 7A adds a small React/TypeScript application in `web/`, built with
Vite 8 and MapLibre GL JS 6. It has no backend or API. Vite exposes the
existing generated package at `data/derived/web-delivery/` as its static
`publicDir`, so the frontend source and generated geospatial products remain
separate.

The map uses a local MapLibre style with no remote basemap or API key. The
2018 browser RGB COG is registered through
`@geomatico/maplibre-cog-protocol` and loaded as a `cog://` raster source at
`/imagery/2018/rgb.tif`. The COG protocol reads the file with HTTP byte-range
requests; Vite development has a small middleware for range responses, while
production uses ordinary static files.

The application loads `/data/summary.json` and
`/data/disturbances.geojson`, fits the map to the GeoJSON WGS84 extent, and
supports hover and single-feature selection with MapLibre feature state. The
selected panel shows only the approved browser properties and keeps coverage
status and limited-imagery warnings visible.

Run locally:

```bash
cd web
npm install
npm run dev
```

Validate and build:

```bash
npm test
npm run lint
npm run typecheck
npm run build
```

Current limitation: this is a 2018-only map state. There is no year switch,
2017↔2018 swipe, NBR/recovery raster layer, full time-series panel, or
recovery chart yet.
