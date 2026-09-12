# Landscape Disturbance & Recovery Monitor

This repository contains the approved first three milestones plus milestones
4A–4F, local milestone-5A recovery analysis, and milestone-6E static data
delivery for the Kårböle/Ljusdal
2018 disturbance case study. It probes
Sentinel-2 STAC and remote COG feasibility, builds August 2017/2018 prototype
products, detects and filters the fixed disturbance objects, and validates
memory-bounded annual Sentinel-2 NBR/NDVI composites for the complete
2017–2026 series. NBR is the primary spectral-recovery indicator, with NDVI
retained as contextual information. The milestone-7A/7B frontend is
implemented under `web/`: a local, map-first React application showing a
synchronized 2017↔2018 RGB browser-COG swipe, disturbance polygons, and
selected browser properties. Analytical layers and recovery charts remain
outside the frontend scope.

## Setup

Python 3.12 or newer is required. Install the package and development tools in
a virtual environment with:

```bash
python -m pip install -e '.[dev]'
```

## Commands

Run the STAC discovery and remote-COG probe:

```bash
python -m landscape_monitor.stac_probe
```

Build the August composite and NBR/dNBR prototype outputs:

```bash
python -m landscape_monitor.build_composite_prototype
```

Build the filtered disturbance masks, polygons, diagnostics, and summary:

```bash
python -m landscape_monitor.build_disturbance
```

Build one explicit annual NBR/NDVI composite (milestone 4A):

```bash
python -m landscape_monitor.build_annual_series --year 2019
```

Build a small explicit set of annual composites sequentially and resumably
(milestone 4B):

```bash
python -m landscape_monitor.build_annual_batch --years 2019 2020
python -m landscape_monitor.build_annual_batch --years 2019 2020 --dry-run
```

Build the local NBR spectral-recovery analysis from the existing annual series
and fixed disturbance objects (milestone 5A):

```bash
python -m landscape_monitor.build_recovery
```

Build one explicit browser-oriented natural-color RGB composite (milestone 6C):

```bash
python -m landscape_monitor.build_rgb_imagery --year 2017
python -m landscape_monitor.build_rgb_imagery --year 2018
python -m landscape_monitor.build_rgb_imagery --year 2020
python -m landscape_monitor.build_rgb_imagery --year 2023
python -m landscape_monitor.build_rgb_imagery --year 2026
```

The command requires one explicit benchmark year and builds years sequentially;
there is no implicit all-years mode. RGB presentation products use a fixed
10 m grid and the approved `0.01–0.22`, gamma `1.0` display transform.

Convert one approved local RGB master into a static MapLibre-oriented browser
COG (milestone 6D):

```bash
python -m landscape_monitor.build_web_imagery --year 2017
```

This local-only command writes EPSG:3857 three-band RGB COGs under
`data/derived/web-delivery/`, with one shared grid, internal overviews, and
explicit RGB nodata. It does not build frontend code or access STAC or remote
EO resources. See [`docs/web-imagery-delivery.md`](docs/web-imagery-delivery.md).

Build the static vector/JSON frontend data package (milestone 6E):

```bash
python -m landscape_monitor.build_web_data
```

This local-only command packages the approved disturbance polygons, compact
NBR/recovery time series, landscape summary, and deterministic manifest under
`data/derived/web-delivery/data/`. It preserves the original WGS84 polygon
topology and applies only QA-gated coordinate rounding. It does not build
frontend code or access network resources. See
[`docs/web-data-delivery.md`](docs/web-data-delivery.md).

Build the analytical browser COG package (milestone 6F):

```bash
python -m landscape_monitor.build_web_rasters
python -m landscape_monitor.build_web_rasters --force
```

This local-only command creates ten annual NBR COGs, ten annual spectral
recovery COGs, and the fixed 2017→2018 spectral dNBR COG on one native-density
analytical EPSG:3857 grid. Values remain float32 and raw; transparency uses an
internal mask and colorization is deferred to the frontend. It does not build
frontend code or access STAC or remote EO resources. See
[`docs/web-raster-delivery.md`](docs/web-raster-delivery.md).

Run the milestone-7B frontend locally (requires Node.js 24+ for the comparison
package):

```bash
cd web
npm install
npm run dev
```

Validate or build the frontend:

```bash
cd web
npm test
npm run lint
npm run typecheck
npm run build
```

The frontend consumes the existing ignored static package at
`data/derived/web-delivery/`; it does not regenerate analytical or delivery
data. Milestone 7B adds only the fixed 2017-before / 2018-after swipe
comparison; there is no year switching, analytical layer, or recovery chart.
See
[`docs/frontend.md`](docs/frontend.md).

Run tests and lint checks:

```bash
pytest
ruff check .
```

Configuration is in [`config/project.toml`](config/project.toml). Generated
STAC inventory is written to `data/inventory/`; prototype outputs are written
to `data/derived/prototype/`, disturbance outputs to
`data/derived/disturbance/`, milestone-4A annual outputs to
`data/derived/annual/`, local recovery analysis to `data/derived/recovery/`,
and RGB presentation products to `data/derived/web-imagery/`; browser delivery
COGs, imagery manifest, and the static vector/JSON package are written
separately under `data/derived/web-delivery/`. Analytical browser COGs use a
separate 20 m-derived Web Mercator grid from the RGB imagery.
Temporary
date-level derived products are written
under `data/.tmp/annual/` and removed after a successful or failed run unless
explicit diagnostic retention is requested. These reproducible build
outputs are intentionally excluded from Git; see [`data/README.md`](data/README.md).
