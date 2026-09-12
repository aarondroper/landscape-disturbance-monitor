# Landscape Disturbance Monitor

An interactive case study of the 2018 disturbance landscape around
Kårböle/Ljusdal in Hälsingland, Sweden. The project uses Sentinel-2 imagery to
detect a fixed 2017→2018 spectral disturbance and examine spectral recovery
from 2017 through 2026 in a React, TypeScript, and MapLibre application.

## What it demonstrates

The repository combines cloud-hosted Sentinel-2/STAC discovery, reproducible
raster processing, project-derived disturbance objects, annual recovery
statistics, Cloud Optimized GeoTIFF (COG) delivery, and a static geospatial
frontend.

## Application

The frontend has three focused modes:

- **Compare** — swipe 2017 and 2018 natural-color imagery.
- **Disturbance** — inspect the fixed 2017→2018 dNBR disturbance layer and
  select one of 80 project-derived objects.
- **Recovery** — switch annual spectral-recovery COGs and inspect the selected
  object’s NBR and recovery timeline.

## Methodology

The disturbance rule retains pixels where `NBR_2017 > 0.30` and
`dNBR = NBR_2017 - NBR_2018 >= 0.30`, then keeps 8-connected components of at
least 5 ha. The resulting objects are derived for this case study; they are
not an official fire perimeter.

For each year, spectral recovery is calculated as:

```text
(NBR_y - NBR_2018) / (NBR_2017 - NBR_2018)
```

This is a spectral recovery measure, not ecological recovery. Values are not
clamped, so values below 0 and above 1 are possible. The detailed processing,
quality checks, and limitations are documented in [`docs/`](docs/).

## Data

The analysis uses Copernicus Sentinel-2 Level-2A data discovered through the
Element 84 Earth Search STAC API. It builds August annual composites for
2017–2026 over the fixed Kårböle/Ljusdal case-study area. Natural-color
presentation imagery is generated for benchmark years 2017, 2018, 2020, 2023,
and 2026.

## Architecture

Python geospatial processing produces a reproducible package of analytical
rasters, browser COGs, and JSON/GeoJSON. The React/MapLibre frontend reads that
package as static assets; no backend or API is required. COGs are intended for
range-capable object storage in deployment, while local development serves the
same package through Vite.

## Repository structure

```text
config/   project configuration
src/      Python analysis and delivery builders
tests/    Python tests
docs/     methodology, delivery, and deployment notes
web/      React/TypeScript/MapLibre frontend
deploy/   deployment configuration examples
```

## Running the project

### Python analysis environment

Python 3.12 or newer is required. From a virtual environment:

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```

The main commands are:

```bash
python -m landscape_monitor.stac_probe
python -m landscape_monitor.build_composite_prototype
python -m landscape_monitor.build_disturbance
python -m landscape_monitor.build_annual_series --year 2019
python -m landscape_monitor.build_annual_batch --years 2019 2020
python -m landscape_monitor.build_recovery
```

The STAC probe and annual/composite builds read live remote data. See the
technical documentation before running a full 2017–2026 rebuild.

### Frontend development

The frontend requires Node.js 24 or newer for the current comparison package.
The generated local package must exist at `data/derived/web-delivery/` for
the application to display data.

```bash
cd web
npm ci
npm run dev
```

For a production shell build, set `VITE_GEO_ASSET_BASE_URL` to the public
asset origin described in [`docs/deployment.md`](docs/deployment.md).

## Reproducing generated data

Public clones intentionally do not contain `data/derived/`. Derived rasters,
delivery COGs, JSON/GeoJSON packages, and QA images are reproducible outputs,
not source files. A complete rebuild is a live and potentially expensive
workflow:

1. Run `python -m landscape_monitor.stac_probe` to create the local STAC
   inventory.
2. Run `python -m landscape_monitor.build_composite_prototype` and
   `python -m landscape_monitor.build_disturbance`.
3. Run `python -m landscape_monitor.build_annual_batch --years 2017 2018 2019 2020 2021 2022 2023 2024 2025 2026`, then
   `python -m landscape_monitor.build_recovery`.
4. Build each benchmark year with
   `python -m landscape_monitor.build_rgb_imagery --year YEAR`, convert each
   master with `python -m landscape_monitor.build_web_imagery --year YEAR`,
   then run `python -m landscape_monitor.build_web_data` and
   `python -m landscape_monitor.build_web_rasters`.

The exact command options and output contracts are documented in
[`docs/annual-compositing.md`](docs/annual-compositing.md),
[`docs/recovery-analysis.md`](docs/recovery-analysis.md), and the web-delivery
notes in [`docs/`](docs/).

## Testing

```bash
pytest
ruff check .
pip check

cd web
npm test
npm run lint
npm run typecheck
npm run build
```

## Limitations

- Detected objects are project-derived spectral disturbance objects, not an
  official wildfire perimeter or a universal burn-severity product.
- Recovery is spectral recovery, not ecological recovery.
- Later-year valid coverage varies by object; missing pixels are not
  interpolated.
- 2023 and 2026 natural-color presentation imagery has lower visual signal in
  this case study.
- This is a fixed case-study analysis of the 2017→2018 disturbance, not a
  real-time or operational monitoring service.

## Deployment

The split static deployment model, COG range-request requirements, and local
validation workflow are described in
[`docs/deployment.md`](docs/deployment.md).
