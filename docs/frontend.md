# Frontend product

The React/TypeScript application in `web/` is a presentation-ready, map-first
portfolio product. It is built with
Vite 8 and MapLibre GL JS 6. It has no backend or API. Vite exposes the
existing generated package at `data/derived/web-delivery/` as its static
`publicDir`, so the frontend source and generated geospatial products remain
separate.

The map uses a local MapLibre style with no remote basemap or API key. The
top-level view control has three modes: `Compare` (the default), `Disturbance`,
and `Recovery`. Together they provide a compact narrative: Compare shows the
visual before/after, Disturbance shows the spatial magnitude of the fixed
2017→2018 spectral change, and Recovery shows the subsequent annual spectral
trajectory.
Compare remains the vertical two-map `@geoql/maplibre-gl-compare` 0.0.4 view:
the before map shows the 2017 browser RGB COG and the after map shows the 2018
browser RGB COG. Both are registered through
`@geomatico/maplibre-cog-protocol` and loaded as `cog://` raster sources at
`/imagery/2017/rgb.tif` and `/imagery/2018/rgb.tif`. The COG protocol reads
these files with HTTP byte-range requests; Vite development has a small
middleware for range responses, while production uses ordinary static files.

The comparison is one synchronized MapLibre camera: navigation controls are
shown once on the 2018 side, while the compare control clips the two stacked
maps around a draggable vertical divider initialized at 50%. The divider is
also keyboard-accessible as a slider. Disturbance GeoJSON, `promoteId`, fill,
outline, hover state, and selected state are configured identically on both
maps and interactions update both instances from one React selection state.
The browser performs no analytical calculations; it reads the static
time-series package and recovery COGs directly.

The `Disturbance` mode uses one separate `DisturbanceMap` MapLibre instance. It
loads the existing fixed dNBR browser COG from
`/rasters/change/dnbr-2017-2018.tif` through a `cog://` raster source with
256-pixel tiles. The raw single-band float32 values are preserved; a custom
client-side color function only changes display color and alpha. The display
stops are `#466f6b` at ≤−0.4, `#d8d4c6` at 0, `#d3ad62` at 0.30,
`#a76545` at 0.60, and `#6b3d30` at ≥1.0. Display alpha is quiet at 88 near
and below zero, 166 at 0.30, 220 at 0.60, and 228 at the upper endpoint,
with interpolation between these reference levels. Values outside the display
range use endpoint colors only; no analytical clamping or normalization is
performed. The COG's internal mask remains transparent.

The Disturbance legend identifies dNBR = 0.30 as a detection-threshold
component and explicitly notes that detected disturbance also required
`NBR2017 > 0.30`. dNBR is `NBR2017 − NBR2018` and represents spectral change,
not an authoritative burn-severity product. Disturbance has no year slider,
does not reuse Recovery's annual coverage widget, and leaves the complete
2017–2026 selected-object timeline visible without a selected-year highlight.
Its fixed 2018 RGB COG is shown beneath the thematic layer at 0.38 opacity as
restrained spatial context and is labeled `2018 reference imagery`.

The `Recovery` mode uses one separate `RecoveryMap` MapLibre instance. It shares
the study-area fit bounds, disturbance source, promoted IDs, hover/selection
semantics, navigation control, scale control, and selected-disturbance panel
with Compare, but does not display the swipe controller. A small shared camera
snapshot (center, zoom, bearing, pitch) is captured on map movement and applied
when switching modes, so switching views does not reset the working extent.

The application loads `/data/summary.json`, `/data/disturbances.geojson`, and
`/data/disturbance-timeseries.json` once at startup. The time-series package is
parsed into an in-memory lookup keyed by `disturbance_id`; selection only reads
from that lookup and does not recreate the maps or refetch the package. The
selected panel preserves its summary values, then adds a compact SVG timeline
with separate NBR and spectral-recovery plots sharing discrete annual
positions from 2017 through 2026. The selected Recovery year is highlighted
on the timeline without changing the chart’s complete annual series.

Recovery has a compact discrete year slider covering exactly 2017–2026 and
defaults to 2026. It directly loads only the selected browser-ready recovery
COG at `/rasters/recovery/{year}.tif`, using a base-aware `cog://` URL and
256-pixel tiles. Changing years updates the recovery raster source/layer only;
the old raster remains until the new source is ready, then stale annual
sources are removed. No all-years preload or year animation is used.

The recovery COG remains a single-band float32 raw product. A deterministic
client-side custom color function maps the raw values visually through the
restrained stops `#6b4c3b` at 0, `#c7a66b` at 0.5, `#6faaa1` at 1.0, and
`#2f6f68` at 1.5; values outside the range are clamped only for display.
Underlying values remain unbounded for the COG and chart. The COG protocol’s
internal mask is applied after colorization, so missing coverage remains
transparent rather than becoming zero recovery. Fixed 2018 RGB imagery is
shown beneath the thematic layer at reduced opacity as spatial context and is
labeled `2018 reference imagery`; it does not switch with the recovery year.
The selected disturbance’s year-specific coverage status is shown beside the
control, with `Limited valid imagery` for POOR coverage.

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
charted in the frontend.

## Product explanation

The compact `Methodology` action in the header opens a right-side React/CSS
drawer over the map. Its copy is kept in the single
`web/src/components/MethodologyPanel.tsx` component/data structure and covers
the three modes, the project-specific disturbance rule, the exact spectral
recovery formula, the meaning of values below 0 and above 1, coverage QA,
data/source context, and concise limitations. It intentionally does not expose
low-level raster or STAC implementation details.

The drawer has a labelled dialog role, a labelled close button, Escape-to-close,
focus on open, and focus return to the header trigger. The Compare divider, map
mode buttons, recovery year slider, and timeline observation targets remain
keyboard accessible. Coverage is communicated with labels and point/line
shapes as well as color. A reduced-motion media rule keeps the small functional
UI transitions safe for users who request less motion.

Loading and runtime failures use short, identified messages such as
`Unable to load recovery layer` and `Unable to load disturbance data`; raw
exception text is not shown in the interface. A subtle attribution line reads
`Sentinel-2 L2A · Copernicus · via Element 84 Earth Search` in the methodology
drawer.

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

Current functionality: 2017↔2018 RGB before/after swipe comparison, Compare /
Disturbance / Recovery map modes, fixed 2017→2018 dNBR display, annual spectral-recovery COG switching, shared camera
navigation, fixed imagery-state labels, mirrored disturbance hover and
selection, the summary panel, and the selected-disturbance NBR and
spectral-recovery timeline. There is no annual NBR map view, generic layer
control, raster-pixel inspector, year animation, NDVI chart, or backend/API.

The frontend is a static delivery package: browser code reads the
JSON and COG assets directly through local MapLibre styling and HTTP byte-range
access. It does not run analytical calculations, call a project backend, or
regenerate data products. Browser smoke/screenshot QA should be recorded with
the environment-specific validation results for each release.

The automated frontend, Python, and static-package checks run without a
browser executable. Interactive browser and screenshot QA therefore remains
an environment-specific release check.
