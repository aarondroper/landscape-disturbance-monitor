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

The application loads `/data/summary.json`, `/data/disturbances.geojson`, and
`/data/disturbance-timeseries.json` once at startup. The time-series package is
parsed into an in-memory lookup keyed by `disturbance_id`; selection only reads
from that lookup and does not recreate the maps or refetch the package. The
selected panel preserves its summary values, then adds a compact SVG timeline
with separate NBR and spectral-recovery plots sharing discrete annual
positions from 2017 through 2026.

The recovery plot shows the median plus a restrained P10–P90 pixel range. Its
reference levels are 0 (post-disturbance baseline) and 1 (2017 baseline).
Recovery is unbounded, so negative values and values above 1 remain visible.
There is no interpolation or smoothing. GOOD and
USABLE_WITH_COVERAGE_FLAG observations may join the primary trajectory;
POOR observations remain as muted/hollow points and ranges but break the
trusted line. Missing/null observations are not converted to zero and also
break the line. Coverage labels remain “Good coverage”, “Partial coverage”,
and “Poor coverage”; poor years additionally identify limited valid imagery.
NDVI remains available as contextual data in the typed contract but is not
charted in this milestone.

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
selection, the approved summary panel, and the selected-disturbance NBR and
spectral-recovery timeline. There is no year switch, analytical raster layer,
layer control, NDVI chart, or backend/API.
