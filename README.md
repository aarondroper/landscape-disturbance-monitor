# Landscape Disturbance & Recovery Monitor

This repository contains the approved first three milestones plus milestones
4A–4F and the local milestone-5A recovery analysis for the Kårböle/Ljusdal
2018 disturbance case study. It probes
Sentinel-2 STAC and remote COG feasibility, builds August 2017/2018 prototype
products, detects and filters the fixed disturbance objects, and validates
memory-bounded annual Sentinel-2 NBR/NDVI composites for the complete
2017–2026 series. NBR is the primary spectral-recovery indicator, with NDVI
retained as contextual information. Frontend work is not implemented.

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
and RGB presentation products to `data/derived/web-imagery/`. Temporary
date-level derived products are written
under `data/.tmp/annual/` and removed after a successful or failed run unless
explicit diagnostic retention is requested. These reproducible build
outputs are intentionally excluded from Git; see [`data/README.md`](data/README.md).
