# Landscape Disturbance Monitor

Sentinel-2 disturbance detection and spectral recovery for the 2018
Kårböle/Ljusdal wildfire landscape in Hälsingland, Sweden. The repository
combines a reproducible Python geospatial pipeline with a static
React/MapLibre application.

## Live application

[Open the Landscape Disturbance Monitor](https://landscape-disturbance-monitor.pages.dev)

## What it demonstrates

- cloud-native Sentinel-2, STAC, and COG processing;
- memory-bounded annual composites;
- transparent disturbance and spectral-recovery methodology;
- browser-native COG visualization; and
- static JSON/GeoJSON delivery without a backend.

## Application

- **Compare** — swipe 2017 and 2018 natural-color imagery.
- **Disturbance** — inspect fixed 2017→2018 dNBR and select detected
  disturbance areas.
- **Recovery** — switch annual recovery layers and inspect an object’s NBR and
  spectral-recovery trajectory.

## Methodology

The analysis uses Copernicus Sentinel-2 Level-2A data discovered through the
Element 84 Earth Search STAC API. Annual composites cover August 1–31 for
2017–2026 on a shared EPSG:32633, 20 m grid.

The disturbance rule is `NBR_2017 > 0.30` and `dNBR >= 0.30`, followed by
8-neighbour connected components of at least 5 ha. It retains 80
project-derived disturbance objects covering approximately 6,808 ha. NBR is
the primary index; NDVI is contextual.

Spectral recovery is calculated relative to the 2017 NBR baseline:

```text
(NBR_y - NBR_2018) / (NBR_2017 - NBR_2018)
```

Values remain unbounded, and recovery is spectral rather than ecological.
Poor-coverage observations remain available but are flagged. See
[`docs/methodology.md`](docs/methodology.md) for the complete analytical
definition and limitations.

## Architecture

```text
Python processing -> generated static web package -> Cloudflare R2
React/MapLibre shell -> Cloudflare Pages
```

The browser reads static JSON, GeoJSON, and COG assets directly. RGB
presentation imagery uses a separate 10 m workflow; it does not replace the
20 m analytical products. See [`docs/frontend.md`](docs/frontend.md) and
[`docs/deployment.md`](docs/deployment.md).

## Repository structure

```text
config/   project configuration
src/      Python analysis and delivery builders
tests/    Python and frontend tests
docs/     methodology, frontend, and deployment documentation
web/      React/TypeScript/MapLibre frontend
deploy/   deployment configuration examples
```

## Local development

Python 3.12 or newer is required. From a virtual environment:

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```

The frontend requires Node.js 24 or newer:

```bash
cd web
npm ci
npm run dev
```

The generated local package must exist at `data/derived/web-delivery/` for
the application to display geospatial data. See
[`docs/deployment.md`](docs/deployment.md) for the Vite `/geo/` setup.

## Reproducing analytical products

Generated rasters, delivery COGs, JSON/GeoJSON packages, and QA images are
reproducible outputs and intentionally excluded from Git. The workflow reads
live remote data and can be expensive.

The main processing stages are:

```bash
python -m landscape_monitor.stac_probe
python -m landscape_monitor.build_composite_prototype
python -m landscape_monitor.build_disturbance
python -m landscape_monitor.build_annual_batch --years 2017 2018 2019 2020 2021 2022 2023 2024 2025 2026
python -m landscape_monitor.build_recovery
python -m landscape_monitor.build_web_data
python -m landscape_monitor.build_web_rasters
```

Benchmark RGB imagery is built one year at a time with
`landscape_monitor.build_rgb_imagery`, followed by
`landscape_monitor.build_web_imagery`. The exact output contracts and
diagnostic tools are documented in [`docs/methodology.md`](docs/methodology.md).

## Testing

Default checks work from a clean clone without generated raster data:

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
pip check

cd web
npm test
npm run lint
npm run typecheck
npm run build
```

Generated-data checks are optional and run only after the local delivery
package exists:

```bash
python -m landscape_monitor.validate_web_delivery
pytest -m generated_data

cd web
npm run test:generated
```

## Data and provenance

The analytical workflow uses Copernicus Sentinel-2 Level-2A imagery through
Element 84 Earth Search. Generated products remain local or are served from
the configured public object-storage origin; they are not committed to Git.

## Limitations

The detected areas are project-derived spectral disturbance objects, not an
official wildfire perimeter or burn-severity classification. Recovery is
spectral recovery, not ecological recovery. Valid coverage varies by year
and object, and the August composites describe a fixed case study rather than
a real-time monitoring service.

## Deployment

The frontend shell is deployed on Cloudflare Pages and the generated
geospatial package is served from range-capable Cloudflare R2 storage. See
[`docs/deployment.md`](docs/deployment.md) for COG Range/CORS requirements and
production instructions.
