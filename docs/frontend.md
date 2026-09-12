# Frontend foundation

Milestone 7A adds a small React/TypeScript application in `web/`, built with
Vite 8 and MapLibre GL JS 6. It has no backend or API. Vite exposes the
existing generated package at `data/derived/web-delivery/` as its static
`publicDir`, so the frontend source and generated geospatial products remain
separate.

The map uses a local MapLibre style with no remote basemap or API key. A
vertical two-map comparison uses `@geoql/maplibre-gl-compare` 0.0.4: the
before map shows the 2017 browser RGB COG and the after map shows the 2018
browser RGB COG. Both are registered through
`@geomatico/maplibre-cog-protocol` and loaded as `cog://` raster sources at
`/imagery/2017/rgb.tif` and `/imagery/2018/rgb.tif`. The COG protocol reads
both files with HTTP byte-range requests; Vite development has a small
middleware for range responses, while production uses ordinary static files.

The comparison is one synchronized MapLibre camera: navigation controls are
shown once on the 2018 side, while the compare control clips the two stacked
maps around a draggable vertical divider initialized at 50%. The divider is
also keyboard-accessible as a slider. Disturbance GeoJSON, `promoteId`, fill,
outline, hover state, and selected state are configured identically on both
maps and interactions update both instances from one React selection state.
The browser performs no analytical calculations and does not load analytical
NBR, recovery, dNBR, or time-series layers.

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

Current functionality: 2017↔2018 RGB before/after swipe comparison, shared
camera navigation, fixed imagery-state labels, mirrored disturbance hover and
selection, and the approved milestone-7A details panel. There is no year
switch, analytical raster layer, full time-series panel, or recovery chart.
