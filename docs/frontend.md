# Frontend

## Stack

The `web/` application uses React, TypeScript, Vite, MapLibre GL JS,
`@geomatico/maplibre-cog-protocol`, and the MapLibre comparison control. It
uses the locally bundled Source Sans 3 family and plain CSS with shared
design tokens. The frontend has no backend or remote basemap API key.

## Application structure

The desktop layout has a dark left application rail, a central full-height map
stage, and a light right inspector. Smaller screens collapse these areas into
an overlaid responsive layout while preserving the same controls and map
content.

## Modes

**Compare** shows 2017 and 2018 browser-ready RGB COGs with a synchronized
vertical swipe divider. The two maps share camera navigation and disturbance
selection state.

**Disturbance** shows the fixed 2017→2018 spectral dNBR COG over restrained
2018 reference imagery. Detected disturbance boundaries support hover,
selection, and a shared visibility toggle.

**Recovery** shows one annual spectral-recovery COG at a time over 2018
reference imagery. A discrete 2017–2026 year control updates the selected
browser layer without preloading every year.

## Data loading and map architecture

At startup the application loads static summary JSON, disturbance GeoJSON,
and disturbance time-series JSON. Map layers read browser-delivery COGs using
base-aware `cog://` URLs and HTTP byte ranges.

All modes use a local MapLibre style and a shared disturbance GeoJSON source
with promoted feature IDs. Hover and selection use MapLibre feature state,
with readiness checks for each map instance. The selected disturbance remains
in React state while switching modes, and the working camera is shared across
views.

## Inspector and chart

The right inspector presents project context, selected-area metrics, coverage
status, and the annual NBR and spectral-recovery trajectory. Recovery values
below 0 and above 1 remain visible. Poor-coverage observations remain marked
and do not become trusted continuous segments.

The Methodology action opens a labelled, keyboard-accessible drawer with the
project’s analytical definitions, data source, coverage rules, and
limitations.

## Local development

```bash
cd web
npm ci
npm run dev
```

Validate and build the frontend with:

```bash
npm test
npm run lint
npm run typecheck
npm run build
```

The generated package is served locally through Vite under `/geo/`. See
[`deployment.md`](deployment.md) for the asset-base and Range-request setup.

## Accessibility and responsiveness

The mode controls, Compare divider, recovery slider, boundary toggle, timeline
observations, and methodology drawer support keyboard interaction. Focus is
managed when the drawer opens and closes, coverage is communicated with text
and non-color visual cues, and reduced-motion preferences are respected.
